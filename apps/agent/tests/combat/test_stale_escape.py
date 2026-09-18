import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from combat._helpers import _make_combat_state, _resolve_deps, _resolve_round
from sample_fixtures import make_context

import abilities
import combat_turn
import conditions
from session_data import CombatParticipant


def _round_setup(*, grappled: bool):
    state = _make_combat_state(player_hp=25, enemy_hp=18)
    escapee = state.get_participant("player_1")
    grappler = state.get_participant("goblin_scout_1")
    assert escapee is not None and grappler is not None
    escapee.initiative = 10
    grappler.id = "mawling_1"
    grappler.name = "Mawling"
    grappler.initiative = 5
    disabler = CombatParticipant(
        id="player_2",
        name="Bram",
        type="player",
        initiative=20,
        hp_current=24,
        hp_max=24,
        ac=15,
        attributes={"strength": 16, "dexterity": 10},
        level=8,
    )
    state.participants.append(disabler)
    state.initiative_order = [disabler.id, escapee.id, grappler.id]
    state.beat = "declaration"
    if grappled:
        escapee.conditions = conditions.apply_condition([], "grappled", source=grappler.id)
    declarations = {
        disabler.id: {
            "type": "ability",
            "action": "warrior_unstoppable_charge",
            "target_id": grappler.id,
        },
        escapee.id: {"type": "maneuver", "target_id": grappler.id},
        grappler.id: {"type": "defend"},
    }
    return state, declarations


def _player_row(player_id, **_kwargs):
    return {
        "player_id": player_id,
        "class": "warrior",
        "level": 8,
        "stamina": {"current": 10, "max": 10},
        "focus": {"current": 0, "max": 0},
    }


async def _resolve_disabled_target(*, grappled: bool):
    state, declarations = _round_setup(grappled=grappled)
    context = make_context()
    context.userdata.combat_state = state
    deps = _resolve_deps()
    deps["queries"].get_player = AsyncMock(side_effect=_player_row)
    charge = replace(abilities.get_ability("warrior_unstoppable_charge"), applies_condition="stunned")
    real_get_ability = abilities.get_ability

    def get_ability(ability_id):
        return charge if ability_id == charge.id else real_get_ability(ability_id)

    with (
        patch("abilities.get_ability", side_effect=get_ability),
        patch("ability_persistence.owns_elective", AsyncMock(return_value=True)),
        patch("ability_persistence.update_player_resources", AsyncMock()),
        patch("check_resolution_save.roll_participant_save", return_value=SimpleNamespace(success=False)),
        patch("random.randint", side_effect=[20, 1]) as maneuver_roll,
    ):
        await combat_turn._declare_phase_impl(context, declarations, mutations=deps["mutations"])
        assert "maneuver_intent" not in declarations["player_1"]
        # The gate's stamp is what the resolver reads a beat later, across a JSONB round-trip:
        # it has to land as a plain string, and land only on the escape.
        persisted = json.loads(json.dumps(context.userdata.combat_state.to_dict()))
        expected_intent = "escape" if grappled else None
        assert persisted["pending_declarations"]["player_1"].get("maneuver_intent") == expected_intent
        result = await _resolve_round(context, **deps)

    assert not isinstance(result, tuple)
    packet = next(packet for packet in result["packets"] if packet["actor_id"] == "player_1")
    grappler = context.userdata.combat_state.get_participant("mawling_1")
    assert grappler is not None
    return packet, grappler, maneuver_roll


@pytest.mark.asyncio
async def test_escape_after_grappler_was_disabled_reports_already_released_without_a_shove():
    packet, grappler, maneuver_roll = await _resolve_disabled_target(grappled=True)

    assert packet["escape"] == "grapple_already_released"
    assert not ({"shove", "actor_total", "target_total"} & packet.keys())
    assert not conditions.has_condition(grappler.conditions, "prone")
    maneuver_roll.assert_not_called()


@pytest.mark.asyncio
async def test_ordinary_shove_against_a_newly_disabled_target_still_resolves():
    packet, grappler, maneuver_roll = await _resolve_disabled_target(grappled=False)

    assert packet["shove"] == "knocked_prone"
    assert conditions.has_condition(grappler.conditions, "prone")
    assert maneuver_roll.call_count == 2
