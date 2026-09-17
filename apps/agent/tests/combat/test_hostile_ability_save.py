import json
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from combat._helpers import _damage_resolver, _fake_db_mod
from livekit.agents.llm import ToolError
from sample_fixtures import make_context

import combat_turn
import conditions
from check_resolution_save import SavingThrowResult
from session_data import CombatParticipant, CombatState


def _participant(pid, name, kind, initiative, *, hp=20, fallen=False):
    return CombatParticipant(
        id=pid,
        name=name,
        type=kind,
        initiative=initiative,
        hp_current=hp,
        hp_max=20,
        ac=13,
        attributes={"strength": 16, "dexterity": 10},
        level=8 if pid == "player_1" else 1,
        is_fallen=fallen,
        action_pool=[{"name": "Strike", "damage": "1d6", "damage_type": "bludgeoning"}],
    )


def _state(target_id="foe", *, extra=None):
    participants = [
        _participant("player_1", "Brann", "player", 15),
        _participant("foe", "Ogre", "enemy", 10),
        *(extra or []),
    ]
    return CombatState(
        combat_id="charge_test",
        participants=participants,
        initiative_order=[p.id for p in sorted(participants, key=lambda p: -p.initiative)],
        beat="resolution",
        pending_declarations={
            "player_1": {
                "type": "ability",
                "action": "warrior_unstoppable_charge",
                "target_id": target_id,
            }
        },
    )


def _deps(state):
    resolver = _damage_resolver(3)
    queries = MagicMock()
    queries.get_player = AsyncMock(
        return_value={
            "player_id": "player_1",
            "class": "warrior",
            "level": 8,
            "stamina": {"current": 10, "max": 10},
            "focus": {"current": 0, "max": 0},
        }
    )
    mutations = MagicMock()
    mutations.save_combat_state = AsyncMock()
    mutations.update_player_hp = AsyncMock()
    break_mod = MagicMock()
    break_mod.break_concentration_on_damage = AsyncMock(return_value=None)
    break_mod.break_concentration_on_incapacitation = AsyncMock(return_value=None)
    context = make_context()
    context.userdata.combat_state = state
    return context, {
        "resolver": resolver,
        "queries": queries,
        "mutations": mutations,
        "concentration_break_mod": break_mod,
        "db_mod": _fake_db_mod(),
    }


def _save(success):
    return SavingThrowResult(
        save_type="strength",
        roll=15 if success else 5,
        modifier=0,
        total=15 if success else 5,
        dc=13,
        success=success,
        margin=2 if success else -8,
        effect_applied=None if success else "prone",
        narrative_hint="",
    )


async def _resolve_charge(success, *, landing=True):
    state = _state()
    context, deps = _deps(state)
    save = MagicMock(return_value=_save(success))
    update = AsyncMock()
    with ExitStack() as stack:
        stack.enter_context(patch("check_resolution_save.roll_participant_save", save))
        stack.enter_context(patch("ability_persistence.update_player_resources", update))
        stack.enter_context(patch("ability_persistence.owns_elective", AsyncMock(return_value=True)))
        if not landing:
            stack.enter_context(patch("combat_ability._land_condition_on_one", return_value=False))
        raw = await combat_turn._resolve_phase_impl(context, **deps)
    assert isinstance(raw, str)
    payload = json.loads(raw)
    return context.userdata.combat_state, payload["packets"][0], save, update, deps


@pytest.mark.asyncio
async def test_failed_save_lands_prone_at_dc_13_and_spends_without_attack():
    state, packet, save, update, deps = await _resolve_charge(False)
    target = state.get_participant("foe")

    assert packet["condition_inflicted"] == "prone"
    assert conditions.has_condition(target.conditions, "prone")
    save.assert_called_once_with(target, "strength", 13, "prone")
    update.assert_awaited_once()
    call = update.await_args
    assert call is not None
    assert call.args == ("player_1",)
    assert call.kwargs["stamina"] == 6
    assert call.kwargs["focus"] is None
    assert call.kwargs["conn"] is not None
    deps["resolver"].resolve_attack.assert_not_called()
    deps["mutations"].update_player_hp.assert_not_awaited()
    assert not ({"attack", "damage"} & packet.keys())


@pytest.mark.asyncio
async def test_made_save_resists_and_still_spends():
    state, packet, _save_mock, update, _deps_map = await _resolve_charge(True)

    assert packet["condition_resisted"] == "prone"
    assert not conditions.has_condition(state.get_participant("foe").conditions, "prone")
    call = update.await_args
    assert call is not None
    assert call.kwargs["stamina"] == 6


@pytest.mark.asyncio
async def test_failed_save_with_no_landing_reports_immunity():
    _state_after, packet, _save_mock, _update, _deps_map = await _resolve_charge(False, landing=False)

    assert packet["condition_immune"] == "prone"
    assert "condition_inflicted" not in packet


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("target_id", "extra"),
    [
        (None, []),
        ("player_1", []),
        ("ally", [_participant("ally", "Scout", "companion", 20)]),
        ("fallen", [_participant("fallen", "Fallen foe", "enemy", 8, hp=0, fallen=True)]),
    ],
)
async def test_invalid_target_refuses_before_any_packet_write(target_id, extra):
    state = _state(target_id, extra=extra)
    if any(p.id == "ally" for p in extra):
        state.pending_declarations["ally"] = {"type": "attack", "action": "Strike", "target_id": "foe"}
    context, deps = _deps(state)

    with (
        patch("check_resolution_save.roll_participant_save") as save,
        patch("ability_persistence.update_player_resources", new_callable=AsyncMock) as update,
        patch("ability_persistence.owns_elective", AsyncMock(return_value=True)),
        pytest.raises(ToolError, match="standing foe"),
    ):
        await combat_turn._resolve_phase_impl(context, **deps)

    save.assert_not_called()
    update.assert_not_awaited()
    deps["resolver"].resolve_attack.assert_not_called()
    deps["mutations"].update_player_hp.assert_not_awaited()
    deps["mutations"].save_combat_state.assert_awaited_once()
    recovered = deps["mutations"].save_combat_state.await_args.args[1]
    assert recovered["beat"] == "declaration"
    assert recovered["pending_declarations"] == {}
