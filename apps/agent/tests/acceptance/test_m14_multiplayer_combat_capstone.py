"""Capstone: M14 multiplayer combat E2E (auto-marked acceptance, per-run Postgres testcontainer).

Proves the M14 seams (stories 001-008) COMPOSE end-to-end for a TWO-PC party on one seeded
testcontainer DB:

- AC1: two PCs enter one combat -> both are player participants in initiative (combat_init reads
  session.party.member_ids as the participation SSOT).
- AC2: both act through the phase loop and each PC's Resonance decays against its OWN pool
  (per-member decay, story-004).
- AC3: the party is wiped and each fallen PC resurrects at its OWN 4-tier anchor with an independent
  death cost (story-005/006 — divergent tier-3 last_rested_settlement_id).
- AC4: an OOC cross-player buff lands on a party ally, and the party gate rejects a non-party target
  (story-007 producer).

Determinism: an injected damage resolver (never real dice). Each scenario uses its OWN id set so the
shared session container stays isolated (reset_db_pool is function-scoped but the migrated container
is session-scoped).
"""

from __future__ import annotations

import json

import pytest
from acceptance.seeds import seed_player
from combat._helpers import _damage_resolver
from sample_fixtures import make_context, make_mock_room

import combat_end
import combat_init
import combat_turn
import condition_produce
import db
import db_mutations
import db_mutations_conditions
import db_mutations_resonance
import db_queries
from combat_events import EventSink
from session_data import CombatParticipant, CombatState

_WEAPON = {"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}


async def _seed_armed(pool, player_id: str, *, location_id: str = "accord_guild_hall") -> None:
    """Seed a default player (seeds.py: level 2, hp 28/28, ac 15) armed with a Longsword so
    combat_init derives a non-empty action_pool from equipment."""
    await seed_player(pool, player_id=player_id, location_id=location_id)
    await pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{equipment}', $2::jsonb) WHERE player_id = $1",
        player_id,
        json.dumps({"main_hand": _WEAPON}),
    )


# --- AC1: two PCs enter one combat ---


async def test_two_pc_combat_init_builds_both_player_participants(reset_db_pool):
    """AC1: a 2-PC party enters combat -> the combat state holds both PCs as player participants,
    each armed from its own equipment."""
    pool = await db.get_pool()
    pc1, pc2 = "cap_m14_init_pc1", "cap_m14_init_pc2"
    await _seed_armed(pool, pc1)
    await _seed_armed(pool, pc2)

    ctx = make_context(pc1, location_id="accord_guild_hall", room=make_mock_room(), party_member_ids=[pc2])
    assert ctx.userdata.party.member_ids == [pc1, pc2]  # 2-member party is the participation SSOT

    raw = await combat_init._start_combat_impl(ctx, "hollow_wisp", "A hollow wisp coalesces from the drift.")
    assert isinstance(raw, tuple)  # hostile encounter -> combat handoff

    cs = ctx.userdata.combat_state
    assert cs is not None
    players = [p for p in cs.participants if p.type == "player"]
    assert {p.id for p in players} == {pc1, pc2}  # one player participant per party member
    assert all(p.action_pool for p in players)  # each PC armed from its own equipment


# --- AC2: phase loop + per-member Resonance decay ---


async def test_two_pc_phase_loop_decays_each_resonance_independently(reset_db_pool):
    """AC2: both PCs act over a phase; each PC's Resonance decays against its OWN pool (distinct
    starting values stay distinct + are persisted per member)."""
    pool = await db.get_pool()
    pc1, pc2 = "cap_m14_res_pc1", "cap_m14_res_pc2"
    await _seed_armed(pool, pc1)
    await _seed_armed(pool, pc2)

    ctx = make_context(pc1, location_id="accord_guild_hall", room=make_mock_room(), party_member_ids=[pc2])
    raw = await combat_init._start_combat_impl(ctx, "hollow_wisp", "A hollow wisp coalesces from the drift.")
    assert isinstance(raw, tuple)
    cs = ctx.userdata.combat_state
    enemy = next(p for p in cs.participants if p.type == "enemy")

    # Seed DISTINCT resonance per member (in-memory base the decay reads + persisted DB baseline).
    bases = {pc1: 9, pc2: 6}
    for m in ctx.userdata.party.members:
        m.resonance.current = bases[m.player_id]
        await db_mutations_resonance.update_player_resonance(m.player_id, bases[m.player_id], conn=pool)

    # Drive one phase. Small fixed damage so nobody dies (wisp 22 HP, PCs 28 HP) -> combat continues
    # and the phase WRAP fires the per-member Resonance decay.
    decls = {
        pc1: {"type": "attack", "action": "Longsword", "target_id": enemy.id},
        pc2: {"type": "attack", "action": "Longsword", "target_id": enemy.id},
        enemy.id: {"type": "attack", "action": enemy.action_pool[0]["name"], "target_id": pc1},
    }
    await combat_turn._declare_phase_impl(ctx, decls)
    result = await combat_turn._resolve_phase_impl(ctx, resolver=_damage_resolver(3))
    assert isinstance(result, str)  # combat continues (no wipe/victory this phase)

    post = {m.player_id: m.resonance.current for m in ctx.userdata.party.members}
    assert post[pc1] < bases[pc1] and post[pc2] < bases[pc2]  # each decayed from its own base
    assert post[pc1] != post[pc2]  # independent pools — distinct bases stay distinct
    for pid in (pc1, pc2):
        db_res = (await db_mutations_resonance.read_player_resonance(pid, conn=pool))["current"]
        assert db_res == post[pid]  # persisted per member (own pool)


# --- AC3: party wipe -> per-anchor resurrection ---


def _fallen_player(player_id: str) -> CombatParticipant:
    return CombatParticipant(
        id=player_id, name=player_id, type="player", initiative=12, hp_current=0, hp_max=28, ac=15, is_fallen=True
    )


async def _seed_for_wipe(pool, player_id: str, last_rested: str) -> None:
    """Seed a player whose death site is off-catalog (tiers 1-2 fall through) with a DISTINCT
    in-catalog last_rested settlement, so each member resurrects at its OWN tier-3 anchor."""
    await seed_player(pool, player_id=player_id, location_id="off_catalog_wilds")
    await pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{last_rested_settlement_id}', $2::jsonb) WHERE player_id = $1",
        player_id,
        json.dumps(last_rested),
    )


async def test_party_wipe_resurrects_each_member_at_own_anchor(reset_db_pool):
    """AC3: a 2-PC party wipe resurrects BOTH fallen PCs, each at its own divergent tier-3 anchor,
    with an independent death recorded."""
    pool = await db.get_pool()
    pc1, pc2 = "cap_m14_wipe_pc1", "cap_m14_wipe_pc2"
    await _seed_for_wipe(pool, pc1, "millhaven")
    await _seed_for_wipe(pool, pc2, "accord_guild_hall")

    ctx = make_context(pc1, location_id="off_catalog_wilds", room=make_mock_room(), party_member_ids=[pc2])
    enemy = CombatParticipant(
        id="cap_m14_wipe_wisp", name="Wisp", type="enemy", initiative=10, hp_current=0, hp_max=22, ac=14, is_fallen=True
    )
    cs = CombatState(
        combat_id="cap_m14_wipe_combat",
        participants=[_fallen_player(pc1), _fallen_player(pc2), enemy],
        initiative_order=[pc1, pc2, "cap_m14_wipe_wisp"],
    )
    ctx.userdata.combat_state = cs

    async with db.transaction() as conn:
        await combat_end._end_combat_db(
            ctx.userdata, cs, "defeat", mutations=db_mutations, queries=db_queries, conn=conn, sink=EventSink()
        )

    # Both members revived at their OWN anchors, each with an independent death recorded.
    row1 = await db_queries.get_player(pc1, conn=pool)
    row2 = await db_queries.get_player(pc2, conn=pool)
    assert row1 is not None and row2 is not None
    assert row1["location_id"] == "millhaven"  # PC1's own tier-3 anchor
    assert row2["location_id"] == "accord_guild_hall"  # PC2's own tier-3 anchor (divergent)
    assert row1["death_history"]["count"] == 1
    assert row2["death_history"]["count"] == 1


# --- AC4: OOC cross-player buff + party gate ---


async def test_ooc_buff_lands_on_ally_and_gate_rejects_non_party_target(reset_db_pool):
    """AC4: an OOC blessed buff lands on a party ally; the party gate refuses a non-party target."""
    pool = await db.get_pool()
    caster, ally, stranger = "cap_m14_buff_caster", "cap_m14_buff_ally", "cap_m14_buff_stranger"
    await seed_player(pool, player_id=caster)
    await seed_player(pool, player_id=ally)
    caster_row = await db_queries.get_player(caster, conn=pool)
    assert caster_row is not None

    # Buff a party ally -> Blessed lands on the ally's players.data conditions SSOT.
    voiced = await condition_produce.produce_ooc_condition(
        "blessed",
        "divine_bless",
        target_id=ally,
        target_ids=None,
        caster_row=caster_row,
        caster_id=caster,
        party_member_ids=[caster, ally],
        companion_id=None,
        conn=pool,
    )
    assert ally in voiced
    ally_conditions = await db_mutations_conditions.read_player_conditions(ally, conn=pool)
    assert "blessed" in [c["type"] for c in ally_conditions]

    # The party gate refuses a target that is neither a party member nor the caster's companion.
    with pytest.raises(ValueError):
        await condition_produce.produce_ooc_condition(
            "blessed",
            "divine_bless",
            target_id=stranger,
            target_ids=None,
            caster_row=caster_row,
            caster_id=caster,
            party_member_ids=[caster, ally],
            companion_id=None,
            conn=pool,
        )
