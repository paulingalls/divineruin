"""Capstone: M18 multiplayer combat completeness E2E (auto-marked acceptance, per-run Postgres
testcontainer). Drives the REAL phase-loop-to-defeat flow for a live 2-PC party — NOT
`combat_end._end_combat_db` directly (the milestone constraint the M14 wipe capstone violated).

Every scenario enters combat via `combat_init._start_combat_impl` and advances it with the
production `combat_turn._declare_phase_impl` / `_resolve_phase_impl`, so the engine's wrap gate is
what decides the outcome. Determinism comes from an injected resolver (never real dice): PCs are
seeded at 3 HP so one forced enemy hit drops each. For the wipe, the PCs DEFEND (deal no damage) so
the enemy never falls and the run ends in DEFEAT — not victory — while a `_lethal_resolver` lands
instant-death overkill blows (is_dead), which also exercises story-003's is_dead resurrection
collector through the real flow. The gate/concentration scenarios use `_damage_resolver(3)`.

Proves M18 stories 002-004 compose through the real flow:
- AC1: the all-players-down gate (story-002) — one member falls, one stands -> combat CONTINUES.
- AC2: the phase loop reaches a full wipe -> per-member resurrection (story-003/005) fires through
  the real defeat path, each PC revived at its OWN divergent tier-3 anchor.
- AC3: a non-primary concentrating member takes the breaking hit -> only THAT member's spell breaks
  (story-004), keyed on the damaged member through the production `combat_support` damage site.

Each scenario uses its OWN id set so the shared session container stays isolated (reset_db_pool is
function-scoped; the migrated container is session-scoped).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from acceptance.seeds import seed_player
from combat._helpers import _damage_resolver
from sample_fixtures import make_context, make_mock_room

import combat_init
import combat_turn
import db
import db_mutations_concentration
import db_queries
from check_resolution_attack import AttackResult

_WEAPON = {"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}
_CONC_SPELL = "arcane_hold_person"  # a real concentration spell with no applied condition
_ENCOUNTER = "hollow_wisp"
_DEFEND = {"type": "defend"}  # a non-attacking declaration — the PC deals no damage this phase


def _lethal_resolver():
    """A resolve_attack stand-in whose every strike is an instant-death overkill blow (overkill far
    exceeds any hp_max, so combat_support flags the target ``is_dead`` — the REAL M4.4 mechanic).

    Used only for the enemy's strikes in the wipe: the PCs DEFEND (no attack), so the enemy takes no
    damage and the fight ends in DEFEAT, not victory. Instant-death also exercises story-003's
    is_dead resurrection collector (is_fallen OR is_dead) through the real flow."""
    result = AttackResult(
        hit=True,
        roll=15,
        attack_modifier=3,
        attack_total=18,
        target_ac=15,
        damage=9999,
        damage_type="slashing",
        target_hp_remaining=0,
        target_killed=True,
        overkill=9999,
        narrative_hint="A killing blow.",
    )
    r = MagicMock()
    r.resolve_attack = MagicMock(return_value=result)
    return r


async def _seed_pc(pool, player_id: str, *, location_id: str, last_rested: str | None = None, hp_current: int = 3):
    """Seed a PC armed with a Longsword (so combat_init derives an action_pool), at ``hp_current`` HP
    (default 3 so one forced 3-damage enemy hit drops it). For the wipe scenario pass an off-catalog
    ``location_id`` + a distinct in-catalog ``last_rested`` so each member resurrects at its OWN
    tier-3 anchor. Purpose-built for the low-HP wipe drive — not the M14 capstone's 28-HP helper."""
    await seed_player(pool, player_id=player_id, location_id=location_id)
    await pool.execute(
        "UPDATE players SET data = jsonb_set(jsonb_set(data, '{equipment}', $2::jsonb), "
        "'{hp,current}', $3::jsonb) WHERE player_id = $1",
        player_id,
        json.dumps({"main_hand": _WEAPON}),
        json.dumps(hp_current),
    )
    if last_rested is not None:
        await pool.execute(
            "UPDATE players SET data = jsonb_set(data, '{last_rested_settlement_id}', $2::jsonb) WHERE player_id = $1",
            player_id,
            json.dumps(last_rested),
        )
    return player_id


def _enemy_of(cs):
    return next(p for p in cs.participants if p.type == "enemy")


def _attack(action: str, target_id: str) -> dict:
    return {"type": "attack", "action": action, "target_id": target_id}


async def test_all_players_down_gate_holds_one_down_one_up(reset_db_pool):
    """AC1: driving the REAL phase loop, when ONE member falls but ONE still stands, combat does NOT
    end (the all-players-down gate, story-002) — resolve_phase returns a continuing str and keeps
    session.combat_state set."""
    pool = await db.get_pool()
    pc1, pc2 = "cap_m18_gate_pc1", "cap_m18_gate_pc2"
    await _seed_pc(pool, pc1, location_id="accord_guild_hall", hp_current=3)
    await _seed_pc(pool, pc2, location_id="accord_guild_hall", hp_current=28)  # healthy, survives the phase

    ctx = make_context(pc1, location_id="accord_guild_hall", room=make_mock_room(), party_member_ids=[pc2])
    raw = await combat_init._start_combat_impl(ctx, _ENCOUNTER, "A hollow wisp coalesces from the drift.")
    assert isinstance(raw, tuple)  # hostile encounter -> combat handoff
    enemy = _enemy_of(ctx.userdata.combat_state)

    await combat_turn._declare_phase_impl(
        ctx,
        {
            pc1: _attack("Longsword", enemy.id),
            pc2: _attack("Longsword", enemy.id),
            enemy.id: _attack(enemy.action_pool[0]["name"], pc1),  # enemy drops pc1 only
        },
    )
    result = await combat_turn._resolve_phase_impl(ctx, resolver=_damage_resolver(3))

    assert isinstance(result, str)  # combat CONTINUES — defeat did not fire on a partial down
    assert ctx.userdata.combat_state is not None
    parts = {p.id: p for p in ctx.userdata.combat_state.participants}
    assert parts[pc1].is_fallen or parts[pc1].is_dead  # pc1 dropped
    assert not (parts[pc2].is_fallen or parts[pc2].is_dead)  # pc2 still standing


async def test_real_phase_loop_wipe_resurrects_each_member(reset_db_pool):
    """AC2: drive the phase loop to a FULL wipe through the real flow — phase 1 drops pc1 (combat
    continues), phase 2 drops pc2 (all players down -> the wrap gate reports DEFEAT). The real defeat
    path (_end_combat_db, reached from inside resolve_phase) resurrects EACH member per-member at its
    OWN divergent tier-3 anchor. Per-member loot/currency/conditions reconcile is pinned by
    story-003's fast-lane tests; this capstone proves the defeat FLOW composes + per-member revive."""
    pool = await db.get_pool()
    pc1, pc2 = "cap_m18_wipe_pc1", "cap_m18_wipe_pc2"
    await _seed_pc(pool, pc1, location_id="off_catalog_wilds", last_rested="millhaven", hp_current=3)
    await _seed_pc(pool, pc2, location_id="off_catalog_wilds", last_rested="accord_guild_hall", hp_current=3)

    ctx = make_context(pc1, location_id="off_catalog_wilds", room=make_mock_room(), party_member_ids=[pc2])
    raw = await combat_init._start_combat_impl(ctx, _ENCOUNTER, "A hollow wisp coalesces from the drift.")
    assert isinstance(raw, tuple)
    enemy = _enemy_of(ctx.userdata.combat_state)

    # Both PCs DEFEND every phase (deal no damage) so the enemy survives -> the run ends in DEFEAT,
    # not victory. Phase 1: the enemy instant-kills pc1; pc2 stands -> combat CONTINUES (the
    # all-players-down gate holds — a single terminal-down PC does not end combat).
    await combat_turn._declare_phase_impl(
        ctx,
        {pc1: _DEFEND, pc2: _DEFEND, enemy.id: _attack(enemy.action_pool[0]["name"], pc1)},
    )
    r1 = await combat_turn._resolve_phase_impl(ctx, resolver=_lethal_resolver())
    assert isinstance(r1, str)  # combat continues
    assert ctx.userdata.combat_state is not None

    # Phase 2: the enemy instant-kills pc2 -> ALL players terminally down -> DEFEAT via the real wrap
    # gate. pc1 is already dead (omitted from the declaration; the engine skips it).
    await combat_turn._declare_phase_impl(
        ctx,
        {pc2: _DEFEND, enemy.id: _attack(enemy.action_pool[0]["name"], pc2)},
    )
    r2 = await combat_turn._resolve_phase_impl(ctx, resolver=_lethal_resolver())

    assert isinstance(r2, tuple)  # combat ENDED (defeat) through the real phase loop
    assert ctx.userdata.combat_state is None

    # Per-member resurrection through the real defeat path: each PC revived at its OWN anchor.
    row1 = await db_queries.get_player(pc1, conn=pool)
    row2 = await db_queries.get_player(pc2, conn=pool)
    assert row1 is not None and row2 is not None
    assert row1["location_id"] == "millhaven"  # pc1's own tier-3 anchor
    assert row2["location_id"] == "accord_guild_hall"  # pc2's own tier-3 anchor (divergent)
    assert row1["death_history"]["count"] == 1
    assert row2["death_history"]["count"] == 1


async def test_non_primary_concentration_breaks_through_real_flow(reset_db_pool):
    """AC3: both PCs concentrate; the enemy incapacitates the NON-primary pc2 (0 HP auto-fails the
    CON save) through the production combat_support damage site, which calls
    break_concentration_on_damage(damaged_player_id=pc2). Only pc2's spell breaks; the untouched
    primary's concentration survives — proving story-004's per-member break through the real flow."""
    pool = await db.get_pool()
    pc1, pc2 = "cap_m18_conc_pc1", "cap_m18_conc_pc2"
    await _seed_pc(pool, pc1, location_id="accord_guild_hall", hp_current=28)  # primary, healthy, not targeted
    await _seed_pc(pool, pc2, location_id="accord_guild_hall", hp_current=3)  # non-primary, dropped

    ctx = make_context(pc1, location_id="accord_guild_hall", room=make_mock_room(), party_member_ids=[pc2])
    raw = await combat_init._start_combat_impl(ctx, _ENCOUNTER, "A hollow wisp coalesces from the drift.")
    assert isinstance(raw, tuple)
    enemy = _enemy_of(ctx.userdata.combat_state)

    # Both PCs concentrating (in-memory per-member state + persisted DB row).
    for pid in (pc1, pc2):
        ctx.userdata.member_state(pid).concentration.spell_id = _CONC_SPELL
        await db_mutations_concentration.update_player_concentration(pid, _CONC_SPELL, conn=pool)

    # Enemy targets the NON-primary pc2 for an incapacitating hit; pc1 is not attacked.
    await combat_turn._declare_phase_impl(
        ctx,
        {
            pc1: _attack("Longsword", enemy.id),
            pc2: _attack("Longsword", enemy.id),
            enemy.id: _attack(enemy.action_pool[0]["name"], pc2),
        },
    )
    await combat_turn._resolve_phase_impl(ctx, resolver=_damage_resolver(3))

    # Only pc2's concentration broke (it took the breaking hit); pc1's survives — in memory AND DB.
    assert ctx.userdata.member_state(pc2).concentration.spell_id is None
    assert ctx.userdata.member_state(pc1).concentration.spell_id == _CONC_SPELL
    assert (await db_mutations_concentration.read_player_concentration(pc2, conn=pool))["spell_id"] is None
    assert (await db_mutations_concentration.read_player_concentration(pc1, conn=pool))["spell_id"] == _CONC_SPELL
