"""Charm source identity and positive final damage at the real landing seam."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _call, _ctx_at_resolution, _make_combat_state, _resolve_deps
from sample_fixtures import make_context

import combat_packet
import conditions
from combat_condition_landing import _land_condition_on_one
from combat_phase import ResolutionPacket
from declarations import resolve_declaration
from session_data import CombatState


def charm(source="player_1"):
    return {"type": "charmed", "source": source, "duration": 3}


@pytest.mark.parametrize("source", [None, "", " ", 1, True, [], {}])
def test_malformed_charm_source_refuses_at_condition_read(source):
    with pytest.raises(ValueError, match="Charmed source"):
        conditions.validate_condition_dict(charm(source))


@pytest.mark.parametrize("source", ["Longsword", "Kael", "removed_actor"])
def test_nonparticipant_charm_source_refuses_reload(source):
    state = _make_combat_state()
    state.participants[1].conditions = [charm(source)]
    with pytest.raises(ValueError, match="not a combat participant"):
        CombatState.from_dict(state.to_dict())


def test_real_infliction_seam_authors_actor_identity_and_roundtrips():
    state = _make_combat_state()
    source, target = state.participants
    assert _land_condition_on_one(state, target.id, source, "charmed", "fixture_ability", packet={}, duration=2)
    assert target.conditions == [{"type": "charmed", "source": source.id, "duration": 2, "stacks": 1}]
    loaded = CombatState.from_dict(json.loads(json.dumps(state.to_dict())))
    assert loaded.participants[1].conditions == target.conditions
    assert conditions.tick_conditions(target.conditions)[0] == [charm() | {"duration": 1, "stacks": 1}]
    assert conditions.tick_conditions([charm() | {"duration": 1, "stacks": 1}])[0] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("actor_type", ["player", "enemy", "companion"])
@pytest.mark.parametrize(
    "source,damage,clears", [("player_1", 3, True), ("player_1", 0, False), ("goblin_scout_1", 3, False)]
)
async def test_attack_producer_clears_only_positive_source_damage(source, damage, clears, actor_type):
    state = _make_combat_state(enemy_hp=30)
    state.participants[0].type = actor_type
    state.participants[1].conditions = [charm(source), {"type": "stunned", "duration": 3, "source": "other"}]
    context = make_context()
    context.userdata.combat_state = state
    deps = _resolve_deps(damage=damage)
    packet = ResolutionPacket(
        "player_1", resolve_declaration({"type": "attack", "action": "Longsword", "target_id": "goblin_scout_1"}), 15
    )
    result = await combat_packet._resolve_one_packet(
        context.userdata,
        state,
        packet,
        mutations=deps["mutations"],
        queries=deps["queries"],
        resolver=deps["resolver"],
        concentration_break_mod=deps["concentration_break_mod"],
    )
    assert result["resolved"] is True
    assert conditions.has_condition(state.participants[1].conditions, "charmed") is not clears
    assert conditions.has_condition(state.participants[1].conditions, "stunned")
    assert state.participants[1].hp_current == 30 - damage


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", [0, 3])
async def test_hold_reload_charm_clears_when_damage_lands(damage):
    ctx = _ctx_at_resolution(player_hp=25, enemy_hp=20, reaction_ids=("skirmisher_sidestep", "rogue_uncanny_dodge"))
    state = ctx.userdata.combat_state
    state.participants[0].conditions = [charm("goblin_scout_1")]
    state.pending_declarations["player_1"] = {"type": "defend", "action": "defend"}
    deps = _resolve_deps(damage=damage)
    deps["resonance_mutations"] = MagicMock(update_player_resonance=AsyncMock())
    for _ in range(3):
        await _call(ctx, deps)
    assert conditions.has_condition(ctx.userdata.combat_state.participants[0].conditions, "charmed")
    ctx.userdata.combat_state = CombatState.from_dict(json.loads(json.dumps(ctx.userdata.combat_state.to_dict())))
    await _call(ctx, deps)
    assert conditions.has_condition(ctx.userdata.combat_state.participants[0].conditions, "charmed") is (damage == 0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source,damage,clears", [("player_1", 4, True), ("player_1", 0, False), ("goblin_1", 4, False)]
)
async def test_inner_fire_source_damage_clearance(source, damage, clears):
    from test_draethar_inner_fire import _combat_ctx, _invoke, _mocks, _player

    ctx = _combat_ctx(player_conditions=[charm(source)])
    await _invoke(ctx, *_mocks(_player(), roll_total=damage))
    assert conditions.has_condition(ctx.userdata.combat_state.participants[0].conditions, "charmed") is not clears


@pytest.mark.asyncio
@pytest.mark.parametrize("action_id", ["valid_combined_bite", "valid_half_on_success"])
@pytest.mark.parametrize("source", ["goblin_scout_1", "player_1"])
async def test_enemy_damage_producers_share_source_clearance(action_id, source, monkeypatch):
    from combat import test_combined_actions as producer

    original = producer._make_combat_state

    def charmed_target(**kwargs):
        state = original(**kwargs)
        state.participants[0].conditions = [charm(source)]
        return state

    monkeypatch.setattr(producer, "_make_combat_state", charmed_target)
    state, summary, _, _ = await producer._resolve(producer.ACTIONS[action_id])
    assert summary["damage"] > 0
    assert conditions.has_condition(state.participants[0].conditions, "charmed") is (source != "goblin_scout_1")


@pytest.mark.asyncio
async def test_charm_duration_expires_at_wrap_without_source_damage():
    ctx = _ctx_at_resolution(player_hp=25, enemy_hp=20, reaction_ids=("skirmisher_sidestep", "rogue_uncanny_dodge"))
    ctx.userdata.combat_state.participants[0].conditions = [charm("goblin_scout_1") | {"duration": 1}]
    ctx.userdata.combat_state.pending_declarations["player_1"] = {"type": "defend", "action": "defend"}
    deps = _resolve_deps(damage=0)
    deps["resonance_mutations"] = MagicMock(update_player_resonance=AsyncMock())
    for _ in range(3):
        await _call(ctx, deps)
    assert conditions.has_condition(ctx.userdata.combat_state.participants[0].conditions, "charmed")
    await _call(ctx, deps)
    assert not conditions.has_condition(ctx.userdata.combat_state.participants[0].conditions, "charmed")
    assert ctx.userdata.combat_state.participants[0].hp_current == 25
