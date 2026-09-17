from types import SimpleNamespace
from unittest.mock import patch

import pytest
from combat._helpers import _resolve_deps, _resolve_round

import conditions
from session_data import CombatState
from tests.combat.test_shield_bash_prone import _started_patrol
from tests.combat.test_start_combat import SAMPLE_PLAYER

CAPABILITIES = {"athletics": "Immovable Anchor", "acrobatics": "Perfect Balance"}


async def _state(skill, tier):
    player = {**SAMPLE_PLAYER, "skill_tiers": {skill: tier}}
    ctx = await _started_patrol(player)
    ctx.userdata.combat_state = CombatState.from_dict(ctx.userdata.combat_state.to_dict())
    return ctx


def _packet(result, actor_id):
    return next(row for row in result["packets"] if row["actor_id"] == actor_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("skill", CAPABILITIES)
@pytest.mark.parametrize("tier", ["master", "expert"])
async def test_skill_tier_controls_shove_prone_immunity(skill, tier):
    ctx = await _state(skill, tier)
    state = ctx.userdata.combat_state
    player = state.get_participant("player_1")
    soldier = state.get_participant("ashmark_soldier_1")
    state.beat = "resolution"
    state.pending_declarations = {
        player.id: {"type": "defend"},
        soldier.id: {"type": "maneuver", "target_id": player.id},
    }

    with patch("random.randint", side_effect=[18, 3]):
        result = await _resolve_round(ctx, **_resolve_deps())

    packet = _packet(result, soldier.id)
    immune = tier == "master"
    assert packet["shove"] == ("resisted" if immune else "knocked_prone")
    assert packet.get("prone_immunity") == (CAPABILITIES[skill] if immune else None)
    assert (
        conditions.has_condition(ctx.userdata.combat_state.get_participant(player.id).conditions, "prone") is not immune
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("skill", CAPABILITIES)
@pytest.mark.parametrize("tier", ["master", "expert"])
async def test_skill_tier_controls_shield_bash_prone_immunity(skill, tier):
    ctx = await _state(skill, tier)
    state = ctx.userdata.combat_state
    player = state.get_participant("player_1")
    soldier = state.get_participant("ashmark_soldier_1")
    state.beat = "resolution"
    state.pending_declarations = {
        player.id: {"type": "defend"},
        soldier.id: {"type": "attack", "action": "Shield Bash", "target_id": player.id},
    }

    with patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=1)):
        result = await _resolve_round(ctx, **_resolve_deps())

    packet = _packet(result, soldier.id)
    immune = tier == "master"
    if immune:
        assert packet["condition_immune"] == "prone"
        assert packet["prone_immunity"] == CAPABILITIES[skill]
    else:
        assert packet["condition_inflicted"] == "prone"
        assert "prone_immunity" not in packet
    assert (
        conditions.has_condition(ctx.userdata.combat_state.get_participant(player.id).conditions, "prone") is not immune
    )


@pytest.mark.asyncio
async def test_trained_athletics_does_not_prevent_a_winning_shove():
    ctx = await _state("athletics", "trained")
    state = ctx.userdata.combat_state
    player = state.get_participant("player_1")
    soldier = state.get_participant("ashmark_soldier_1")
    state.beat = "resolution"
    state.pending_declarations = {
        player.id: {"type": "defend"},
        soldier.id: {"type": "maneuver", "target_id": player.id},
    }

    with patch("random.randint", side_effect=[18, 3]):
        result = await _resolve_round(ctx, **_resolve_deps())

    assert _packet(result, soldier.id)["shove"] == "knocked_prone"
