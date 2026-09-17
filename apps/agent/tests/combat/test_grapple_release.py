import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from combat._helpers import _damage_resolver, _make_combat_state, _resolve_deps
from sample_fixtures import make_context

import conditions
from combat_packet import _resolve_one_packet
from combat_phase import ResolutionPacket
from combat_support import _handle_hp_zero
from declarations import Declaration, DeclarationType
from session_data import CombatParticipant

_CATALOG = json.loads((Path(__file__).resolve().parents[4] / "content" / "encounter_templates.json").read_text())


def _hold_person() -> dict:
    return next(
        copy.deepcopy(action)
        for encounter in _CATALOG
        for enemy in encounter["enemies"]
        for action in enemy["action_pool"]
        if action["name"] == "Hold Person"
    )


def _participant(state, participant_id: str) -> CombatParticipant:
    participant = state.get_participant(participant_id)
    assert participant is not None
    return participant


def _release_state():
    state = _make_combat_state(player_hp=25, enemy_hp=5)
    grappler = state.get_participant("goblin_scout_1")
    player = state.get_participant("player_1")
    assert grappler is not None and player is not None
    grappler.id = "mawling_1"
    grappler.name = "Mawling One"
    state.initiative_order = [player.id, grappler.id]
    player.conditions = conditions.apply_condition([], "grappled", source=grappler.id)
    other_target = CombatParticipant(
        id="player_2",
        name="Bram",
        type="player",
        initiative=14,
        hp_current=20,
        hp_max=20,
        ac=14,
        conditions=conditions.apply_condition([], "grappled", source="mawling_2"),
    )
    other_grappler = copy.deepcopy(grappler)
    other_grappler.id = "mawling_2"
    other_grappler.name = "Mawling Two"
    state.participants.extend([other_target, other_grappler])
    return state


@pytest.mark.asyncio
async def test_real_killing_attack_releases_only_the_fallen_grapplers_targets():
    state = _release_state()
    packet = ResolutionPacket(
        actor_id="player_1",
        declaration=Declaration(type=DeclarationType.ATTACK, action="Longsword", target_id="mawling_1"),
        initiative=15,
    )
    deps = _resolve_deps()

    summary = await _resolve_one_packet(
        make_context().userdata,
        state,
        packet,
        mutations=deps["mutations"],
        queries=deps["queries"],
        resolver=_damage_resolver(10),
        concentration_break_mod=deps["concentration_break_mod"],
    )

    assert summary["target_fallen"] is True
    assert summary["released_from_grapple"] == ["player_1"]
    assert not conditions.has_condition(_participant(state, "player_1").conditions, "grappled")
    assert conditions.has_condition(_participant(state, "player_2").conditions, "grappled")


@pytest.mark.asyncio
@pytest.mark.parametrize(("save_success", "released"), [(False, True), (True, False)])
async def test_cannot_act_condition_releases_only_when_it_lands(save_success, released):
    state = _release_state()
    caster = CombatParticipant(
        id="cultist",
        name="Cultist",
        type="enemy",
        initiative=20,
        hp_current=10,
        hp_max=10,
        ac=12,
        action_pool=[_hold_person()],
    )
    state.participants.append(caster)
    packet = ResolutionPacket(
        actor_id=caster.id,
        declaration=Declaration(type=DeclarationType.ATTACK, action="Hold Person", target_id="mawling_1"),
        initiative=20,
    )
    deps = _resolve_deps()
    with patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=20 if save_success else 1)):
        summary = await _resolve_one_packet(
            make_context().userdata,
            state,
            packet,
            mutations=deps["mutations"],
            queries=deps["queries"],
            resolver=deps["resolver"],
            concentration_break_mod=MagicMock(
                break_concentration_on_damage=AsyncMock(return_value=None),
                break_concentration_on_incapacitation=AsyncMock(return_value=None),
            ),
        )

    player = state.get_participant("player_1")
    assert player is not None
    assert conditions.has_condition(player.conditions, "grappled") is not released
    assert summary.get("released_from_grapple") == (["player_1"] if released else None)
    assert conditions.has_condition(_participant(state, "player_2").conditions, "grappled")


def test_hollowed_rise_does_not_release_the_rising_grappler():
    state = _release_state()
    grappler = state.get_participant("mawling_1")
    assert grappler is not None
    grappler.type = "player"
    grappler.hp_current = 0
    grappler.conditions = []
    for _ in range(2):
        grappler.conditions = conditions.apply_condition(grappler.conditions, "hollowed")

    _, rose, released = _handle_hp_zero(
        make_context().userdata,
        state,
        grappler,
        overkill=0,
        was_fallen=False,
        hp_status="defeated",
        sounds=[],
    )

    assert rose is True
    assert released == []
    assert conditions.has_condition(_participant(state, "player_1").conditions, "grappled")
