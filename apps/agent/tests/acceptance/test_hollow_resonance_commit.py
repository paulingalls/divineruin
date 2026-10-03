"""Hollow death/cast ordering, rollback and reload against real Postgres."""

from copy import deepcopy
from dataclasses import asdict
from uuid import uuid4

import pytest
from _hollow_resonance_fixtures import hollow
from acceptance.seeds import seed_player_with_pools
from combat._helpers import _damage_resolver
from sample_fixtures import make_context
from voice_condition_fixtures import participant, place_actors

import combat_events
import combat_turn
import db
import db_mutations
import db_mutations_concentration
import db_mutations_resonance
import db_queries
import resonance_events
import spell_casting
from combat_participant import CombatParticipant
from combat_state import CombatState


@pytest.fixture
async def encounter(reset_db_pool, monkeypatch):
    pool = await db.get_pool()
    ids = [f"hollow_{uuid4().hex}" for _ in range(3)]
    for pid, cls in zip(ids, ("mage", "mage", "warrior"), strict=True):
        await seed_player_with_pools(
            pool, player_id=pid, class_=cls, known_spells=("arcane_magic_missile", "arcane_detect_magic")
        )
    ctx = make_context(ids[0], party_member_ids=ids)
    for i, m in enumerate(ctx.userdata.party.members):
        m.resonance.current = (2, 4, 0)[i]
        m.resonance.flickering_bonus = int(i == 1)
        if i == 1:
            m.concentration.spell_id = "arcane_fly"
            await db_mutations_concentration.update_player_concentration(m.player_id, "arcane_fly", conn=pool)
        await db_mutations_resonance.update_player_resonance(m.player_id, m.resonance.current, conn=pool)
        await db_mutations_resonance.update_player_flickering_bonus(
            m.player_id, m.resonance.flickering_bonus, conn=pool
        )
    players = [CombatParticipant(pid, pid, "player", 30 - i * 10, 28, 28, 15) for i, pid in enumerate(ids)]
    for p in players:
        p.action_pool = [{"name": "Strike", "damage": "1d8", "damage_type": "slashing", "properties": []}]
    enemies = [hollow(f"victim_{i}") for i in range(2)] + [hollow("survivor")]
    state = place_actors(
        CombatState(f"combat_{uuid4().hex}", players + enemies, ids + [e.id for e in enemies], beat="resolution")
    )
    state.pending_declarations = {
        ids[0]: {"type": "attack", "action": "Strike", "target_id": "victim_0"},
        ids[1]: {"type": "ability", "action": "arcane_magic_missile"},
        ids[2]: {"type": "attack", "action": "Strike", "target_id": "victim_1"},
    }
    ctx.userdata.combat_state = state
    await db_mutations.save_combat_state(state.combat_id, state.to_dict(), conn=pool)
    events = []

    async def transport(room, kind, payload, *args, **kwargs):
        events.append((kind, deepcopy(payload)))

    for module in (combat_events, resonance_events, spell_casting):
        monkeypatch.setattr(module, "publish_game_event", transport)
    try:
        yield ctx, ids, events
    finally:
        await db_mutations.delete_combat_state(state.combat_id, conn=pool)
        for pid in ids:
            await pool.execute("DELETE FROM players WHERE player_id=$1", pid)


async def snapshot(ctx, ids):
    pool = await db.get_pool()
    rows = [await db_queries.get_player(pid, conn=pool) for pid in ids]
    state = ctx.userdata.combat_state
    loaded = await db_mutations.load_combat_state(state.combat_id, conn=pool)
    assert loaded is not None
    return rows, asdict(ctx.userdata.party), state.to_dict(), loaded.to_dict(), list(ctx.userdata.recent_events)


async def phase(ctx):
    return await combat_turn._resolve_phase_impl(ctx, resolver=_damage_resolver(1000))


async def assert_rollback(encounter, monkeypatch, *, leak=False, cast_only=False):
    ctx, ids, events = encounter
    if cast_only:
        ctx.userdata.combat_state.pending_declarations = {ids[1]: {"type": "ability", "action": "arcane_detect_magic"}}
        await db_mutations.save_combat_state(ctx.userdata.combat_state.combat_id, ctx.userdata.combat_state.to_dict())
    before = await snapshot(ctx, ids)
    original = db_mutations.save_combat_state

    async def fail_after_write(combat_id, data, *, conn=None):
        await original(combat_id, data, conn=conn)
        if leak:
            ctx.userdata.member_state(ids[1]).resonance.current = 99
            await resonance_events.publish_resonance_changed(ctx.userdata, caster_id=ids[1])
        raise RuntimeError("after writes")

    with monkeypatch.context() as fault:
        fault.setattr(db_mutations, "save_combat_state", fail_after_write)
        with pytest.raises(RuntimeError, match="after writes"):
            await phase(ctx)
    assert await snapshot(ctx, ids) == before
    assert events == []


async def test_cast_rollback_is_atomic(encounter, monkeypatch):
    await assert_rollback(encounter, monkeypatch, cast_only=True)


async def test_death_phase_rollback_is_atomic(encounter, monkeypatch):
    await assert_rollback(encounter, monkeypatch)


async def test_guard_commit_buffering(encounter, monkeypatch):
    with pytest.raises(AssertionError):
        await assert_rollback(encounter, monkeypatch, leak=True)


@pytest.mark.parametrize("cast_first,ward", [(False, False), (True, False), (False, True), (True, True)])
async def test_commit_routes_qualitative_states_and_resume_is_once(encounter, cast_first, ward):
    ctx, ids, events = encounter
    state = ctx.userdata.combat_state
    state.get_participant(ids[1]).initiative = 40 if cast_first else 5
    if ward:
        state.veil_ward = {"source": "test", "rounds_remaining": None}
        for victim in state.participants[3:5]:
            victim.hollow = hollow(creature_id="hollow_veilrender").hollow
    await phase(ctx)
    expected = (4, 7 if ward else 8, 0)
    assert tuple(m.resonance.current for m in ctx.userdata.party.members) == expected
    for pid, value in zip(ids, expected, strict=True):
        assert (await db_mutations_resonance.read_player_resonance(pid))["current"] == value
    pushes = [(kind, payload) for kind, payload in events if kind == "resonance_changed"]
    assert pushes == [
        ("resonance_changed", {"state": "stable", "caster_id": ids[0]}),
        ("resonance_changed", {"state": "flickering", "caster_id": ids[1]}),
    ]
    loaded = await db_mutations.load_combat_state(state.combat_id)
    assert loaded is not None
    assert all(participant(loaded, f"victim_{i}").hollow_death_resolved for i in range(2))
    ctx.userdata.combat_state = loaded
    await phase(ctx)
    assert tuple(m.resonance.current for m in ctx.userdata.party.members) == (3, expected[1] - 1, 0)
    before = [await db_mutations_resonance.read_player_resonance(pid) for pid in ids]
    from combat_events import EventSink
    from combat_support import SaveDamageResult, apply_attack_result

    async with db.transaction() as conn:
        await apply_attack_result(
            ctx.userdata,
            loaded.participants[0],
            {},
            participant(loaded, "victim_0"),
            SaveDamageResult("wisdom", False, 1000, "force", "hit", False, "replay"),
            10,
            combat_state=loaded,
            conn=conn,
            sink=EventSink(),
            publish_roll=False,
        )
    assert [await db_mutations_resonance.read_player_resonance(pid) for pid in ids] == before


async def test_held_damage_reload_preserves_death_receipt(encounter):
    ctx, _ids, _ = encounter
    state = ctx.userdata.combat_state
    state.pending_declarations = {"survivor": {"type": "attack", "action": "Claw", "target_id": "victim_0"}}
    state.get_participant("survivor").action_pool = [
        {"name": "Claw", "damage": "1d8", "damage_type": "slashing", "properties": []}
    ]
    await phase(ctx)
    held = deepcopy(ctx.userdata.combat_state.held_actions)
    assert held and held[0]["declaration"]["target_id"] == "victim_0"
    ctx.userdata.combat_state = await db_mutations.load_combat_state(state.combat_id)
    await phase(ctx)
    assert tuple(m.resonance.current for m in ctx.userdata.party.members) == (2, 4, 0)
    loaded = await db_mutations.load_combat_state(state.combat_id)
    assert loaded is not None
    assert participant(loaded, "victim_0").hollow_death_resolved
    loaded.beat = "narration"
    loaded.held_actions = held
    ctx.userdata.combat_state = loaded
    await phase(ctx)
    assert tuple(m.resonance.current for m in ctx.userdata.party.members) == (1, 3, 0)


@pytest.mark.parametrize("refusal", ["unknown", "focus"])
async def test_refused_cast_leaves_resources_and_events_unchanged(encounter, refusal):
    from livekit.agents.llm import ToolError

    ctx, ids, events = encounter
    state = ctx.userdata.combat_state
    spell_id = "unknown_spell" if refusal == "unknown" else "arcane_magic_missile"
    state.pending_declarations = {ids[1]: {"type": "ability", "action": spell_id}}
    if refusal == "focus":
        pool = await db.get_pool()
        await pool.execute("UPDATE players SET data=jsonb_set(data,'{focus,current}','0') WHERE player_id=$1", ids[1])
    before = [await db_queries.get_player(pid) for pid in ids]
    mirrors = asdict(ctx.userdata.party)
    with pytest.raises(ToolError):
        await phase(ctx)
    assert [await db_queries.get_player(pid) for pid in ids] == before
    assert asdict(ctx.userdata.party) == mirrors
    assert events == []


async def test_guard_pending_total_reads(encounter, monkeypatch):
    import combat_hollow_resonance

    monkeypatch.setattr(combat_hollow_resonance, "current_total", lambda state, caster: caster.resonance.current)
    with pytest.raises(AssertionError):
        await test_commit_routes_qualitative_states_and_resume_is_once(encounter, False, False)


async def test_guard_pending_total_merge(encounter, monkeypatch):
    import combat_hollow_resonance

    monkeypatch.setattr(combat_hollow_resonance, "take_totals", lambda state: {})
    with pytest.raises(AssertionError):
        await test_commit_routes_qualitative_states_and_resume_is_once(encounter, False, False)


async def test_guard_owner_persistence(encounter, monkeypatch):
    _ctx, ids, _ = encounter
    original = db_mutations_resonance.update_player_resonance

    async def wrong_owner(pid, total, *, conn=None):
        await original(ids[0] if pid == ids[1] else pid, total, conn=conn)

    monkeypatch.setattr(db_mutations_resonance, "update_player_resonance", wrong_owner)
    with pytest.raises(AssertionError):
        await test_commit_routes_qualitative_states_and_resume_is_once(encounter, False, False)
