"""Hollow generation through committed spell and damage consumers."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from _hollow_resonance_fixtures import cast, hollow, scenario
from _spell_casting_helpers import _player
from voice_condition_fixtures import place_actors

import spells
from combat_state import CombatState


@pytest.mark.parametrize("distance,bonus", [(0, 1), (5, 1), (5.01, 0)])
async def test_actual_catalog_cast_aura_boundary(distance, bonus):
    ctx, state, _ = scenario(distance=distance)
    result, _, _ = await cast(ctx, state)
    spell = spells.get_spell("arcane_magic_missile")
    assert result.generated == spell.resonance_by_source[spell.source] + bonus
    assert ctx.userdata.resonance.current == 0


@pytest.mark.parametrize("level,expected", [(0, 2), (1, 2), (2, 3), (3, 3)])
async def test_actual_cast_max_stacking(level, expected):
    ctx, state, _ = scenario()
    ctx.userdata.party.primary.corruption_level = level
    second = hollow("second")
    state.participants.append(second)
    place_actors(state)
    result, _, _ = await cast(ctx, state)
    assert result.generated == expected


async def test_actual_cast_cantrip_refusal_and_zero_values():
    from livekit.agents.llm import ToolError

    ctx, state, _ = scenario(creature_id="hollow_shadeling", distance=0)
    result, mutations, persistence = await cast(ctx, state, "arcane_bolt")
    assert result.generated == 0
    mutations.update_player_resonance.assert_not_called()
    persistence.update_player_resources.assert_not_called()
    with pytest.raises(ToolError):
        await cast(ctx, state, focus=0)
    result, _, _ = await cast(ctx, state)
    assert result.generated == 2
    assert state.spatial is not None
    state.spatial["positions"]["hollow"]["x"] = 0.01
    result, _, _ = await cast(ctx, state)
    assert result.generated == 1


async def test_ward_after_aura_and_working_dead_source():
    ctx, state, enemy = scenario()
    state.veil_ward = {"source": "test", "rounds_remaining": None}
    result, _, _ = await cast(ctx, state, "arcane_mist_step")
    assert result.generated == 1
    enemy.is_dead = True
    result, _, _ = await cast(ctx, state, "arcane_magic_missile")
    assert result.generated == 0


async def damage(ctx, state, target, *, queries=None):
    from combat_events import EventSink
    from combat_support import SaveDamageResult, apply_attack_result

    queries = queries or MagicMock(
        get_player=AsyncMock(return_value=_player()), get_player_inventory=AsyncMock(return_value=[])
    )
    mutations = MagicMock(update_player_hp=AsyncMock())
    break_mod = MagicMock(break_concentration_on_damage=AsyncMock(return_value=None))
    return await apply_attack_result(
        ctx.userdata,
        state.participants[0],
        {},
        target,
        SaveDamageResult("wisdom", False, target.hp_max, "force", "impact", False, "test"),
        target.ac,
        combat_state=state,
        conn=object(),
        queries=queries,
        mutations=mutations,
        concentration_break_mod=break_mod,
        sink=EventSink(),
        publish_roll=False,
    )


async def death_twice(monkeypatch):
    import db_mutations_resonance
    from combat_hollow_resonance import current_total

    ctx, state, enemy = scenario()
    writer = AsyncMock()
    monkeypatch.setattr(db_mutations_resonance, "update_player_resonance", writer)
    await damage(ctx, state, enemy)
    assert enemy.is_dead and enemy.is_fallen and enemy.hollow_death_resolved
    assert current_total(state, ctx.userdata.party.primary) == 1
    await damage(ctx, state, enemy)
    assert current_total(state, ctx.userdata.party.primary) == 1
    writer.assert_awaited_once()
    assert ctx.userdata.resonance.current == 0
    return ctx, state, enemy


async def test_distinct_deaths_stack_and_replay_once(monkeypatch):
    from combat_hollow_resonance import current_total

    ctx, state, _ = await death_twice(monkeypatch)
    second = hollow("second")
    state.participants.append(second)
    place_actors(state)
    await damage(ctx, state, second)
    assert current_total(state, ctx.userdata.party.primary) == 2
    loaded = CombatState.from_dict(state.to_dict())
    await damage(ctx, loaded, loaded.get_participant(second.id))
    assert not hasattr(loaded, "_resonance_totals")


@pytest.mark.parametrize("kind", ["player", "companion", "temporary_hollowed", "nonhollow", "zero", "legacy"])
async def test_excluded_and_zero_deaths(monkeypatch, kind):
    import db_mutations_resonance

    ctx, state, enemy = scenario()
    writer = AsyncMock()
    monkeypatch.setattr(db_mutations_resonance, "update_player_resonance", writer)
    if kind in ("player", "companion", "temporary_hollowed"):
        enemy.type = kind
    elif kind == "nonhollow":
        enemy.hollow = None
    elif kind == "zero":
        assert enemy.hollow is not None
        enemy.hollow["resonance_on_death"] = 0
    else:
        enemy.hp_current = 0
        enemy.is_fallen = True
    await damage(ctx, state, enemy)
    writer.assert_not_called()


async def test_guard_aura_inclusion(monkeypatch):
    import combat_hollow_resonance

    monkeypatch.setattr(combat_hollow_resonance, "cast_generation", lambda state, caster, spell, generated: generated)
    with pytest.raises(AssertionError):
        await test_actual_catalog_cast_aura_boundary(5, 1)


async def test_guard_cantrip_exclusion(monkeypatch):
    import combat_hollow_resonance

    original = combat_hollow_resonance.apply_corruption_aura
    monkeypatch.setattr(combat_hollow_resonance, "apply_corruption_aura", lambda g, f, *args: original(g, 1, *args))
    with pytest.raises(AssertionError):
        await test_actual_cast_cantrip_refusal_and_zero_values()


async def test_guard_death_once(monkeypatch):
    import combat_hollow_death

    monkeypatch.setattr(combat_hollow_death, "new_destruction", lambda target, *args: target.hollow is not None)
    with pytest.raises(AssertionError):
        await death_twice(monkeypatch)


async def test_guard_immediate_hollow_destruction(monkeypatch):
    import combat_hollow_death

    original = combat_hollow_death.mark_destroyed

    def leave_alive(target):
        original(target)
        target.is_dead = False

    monkeypatch.setattr(combat_hollow_death, "mark_destroyed", leave_alive)
    with pytest.raises(AssertionError):
        await death_twice(monkeypatch)


async def recipient_scenario(monkeypatch):
    import db_mutations_resonance
    from caster_state import ConcentrationState, ResonanceTrack
    from combat_hollow_resonance import current_total
    from combat_participant import CombatParticipant
    from party_state import PartyMember

    ctx, state, enemy = scenario()
    writer = AsyncMock()
    monkeypatch.setattr(db_mutations_resonance, "update_player_resonance", writer)
    classes = {"player_1": "mage"}
    for pid, _distance, cls, unavailable in [
        ("near", 59, "mage", False),
        ("edge", 60, "bard", False),
        ("far", 61, "mage", False),
        ("martial", 10, "warrior", False),
        ("fallen", 10, "mage", True),
        ("dead", 10, "mage", True),
    ]:
        member = PartyMember(pid, ResonanceTrack(current=2, flickering_bonus=1), ConcentrationState())
        ctx.userdata.party.members.append(member)
        p = CombatParticipant(pid, pid, "player", 15, 0 if unavailable else 20, 20, 14)
        p.is_fallen = unavailable
        p.is_dead = pid == "dead"
        state.participants.append(p)
        classes[pid] = cls
    place_actors(state)
    assert state.spatial is not None
    for pid, distance in [("near", 59), ("edge", 60), ("far", 61)]:
        state.spatial["positions"][pid]["x"] = distance
    queries = MagicMock(get_player=AsyncMock(side_effect=lambda pid, **kw: {**_player(), "class": classes[pid]}))
    await damage(ctx, state, enemy, queries=queries)
    assert {call.args[0]: call.args[1] for call in writer.await_args_list} == {"player_1": 1, "near": 3, "edge": 3}
    assert current_total(state, ctx.userdata.member_state("edge")) == 3
    assert ctx.userdata.member_state("edge").resonance.flickering_bonus == 1
    assert ctx.userdata.member_state("edge").resonance.current == 2


async def test_death_recipients_and_cross_source_caster(monkeypatch):
    await recipient_scenario(monkeypatch)


async def owner_scenario():
    from caster_state import ConcentrationState, ResonanceTrack
    from combat_hollow_resonance import current_total
    from combat_participant import CombatParticipant
    from party_state import PartyMember

    ctx, state, _ = scenario()
    owner = PartyMember("guest", ResonanceTrack(current=4, flickering_bonus=1), ConcentrationState())
    ctx.userdata.party.members.append(owner)
    state.participants.append(CombatParticipant("guest", "Guest", "player", 15, 20, 20, 14))
    place_actors(state)
    result, mutations, _ = await cast(ctx, state, owner=owner)
    assert result.new_resonance == 6
    mutations.update_player_resonance.assert_awaited_once_with(
        "guest", 6, conn=mutations.update_player_resonance.call_args.kwargs["conn"]
    )
    assert current_total(state, owner) == 6
    assert current_total(state, ctx.userdata.party.primary) == 0
    assert owner.resonance.current == 4


async def test_nonprimary_cast_owns_pending_total():
    await owner_scenario()


async def test_guard_owner_routing(monkeypatch):
    import combat_hollow_resonance

    original = combat_hollow_resonance.stage_total
    monkeypatch.setattr(
        combat_hollow_resonance, "stage_total", lambda state, pid, total: original(state, "player_1", total)
    )
    with pytest.raises(AssertionError):
        await owner_scenario()
    import combat_hollow_death

    monkeypatch.setattr(
        combat_hollow_death, "stage_total", lambda state, pid, total: original(state, "player_1", total)
    )
    with pytest.raises(AssertionError):
        await recipient_scenario(monkeypatch)


@pytest.mark.parametrize("working_ward", [False, True])
async def test_actual_cast_uses_working_ward(working_ward):
    from copy import deepcopy

    import ward_resolution

    ctx, state, _ = scenario()
    pristine = deepcopy(state)
    ward = {"source": "test", "rounds_remaining": None}
    pristine.veil_ward = None if working_ward else ward
    ctx.userdata.combat_state = pristine
    state.veil_ward = ward if working_ward else None
    result, _, _ = await cast(ctx, state, ward_mod=ward_resolution)
    assert result.generated == (1 if working_ward else 2)


async def test_ward_floored_death_consumes_receipt_without_write(monkeypatch):
    import db_mutations_resonance

    ctx, state, enemy = scenario()
    state.veil_ward = {"source": "test", "rounds_remaining": None}
    writer = AsyncMock()
    monkeypatch.setattr(db_mutations_resonance, "update_player_resonance", writer)
    await damage(ctx, state, enemy)
    assert enemy.hollow_death_resolved
    writer.assert_not_called()
