"""Capstone: M4.1 phase-loop full lifecycle end-to-end against a real Postgres testcontainer.

Stories 001-005/007-010 shipped the M4.1 4-beat phase machine with unit / mock-conn / single-table
real-PG coverage: the pure advance_combat_phase engine (001), persistence read path (002), the live
CombatAgent phase-loop orchestration (003), the combat prompt (004), crit flags (005), in-combat
Resonance-decay suppression (007), helper cleanup (008), dead HP-path removal (009), and
transactional phase resolution (010). This capstone proves they COMPOSE against ONE seeded
testcontainer (auto-marked `acceptance` by tests/acceptance/conftest.py), exercising the seams the
mocked units can't: combat_init persistence + initiative, the declare/resolve loop against real
players/combat_instances, end_combat's XP + state-delete, and save/reload mid-fight.

Dice are made deterministic by injecting a fixed-damage resolver into _resolve_phase_impl (the DI
seam the unit TestPhaseLoopE2E uses); the real resolve_attack math is unit-tested in
test_rules_attack/test_rules_resolution. Everything else — mutations, queries, the db.transaction
wrapper — runs for real. Each test uses a distinct player_id since the testcontainer DB is shared.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from acceptance.seeds import seed_player
from combat._helpers import _damage_resolver, _resolution_state
from sample_fixtures import make_context

import combat_init
import combat_phase
import combat_turn
import db
import db_mutations
from check_resolution_attack import AttackResult

_WEAPON = {"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}


async def _seed_armed_player(pool, player_id: str) -> None:
    """Seed a player (HP 28) with an equipped weapon so combat_init synthesizes a player
    action_pool (it builds the pool from equipment entries that carry `damage`)."""
    await seed_player(pool, player_id=player_id, location_id="accord_guild_hall")
    await pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{equipment}', $2::jsonb) WHERE player_id = $1",
        player_id,
        json.dumps({"main_hand": _WEAPON}),
    )


async def test_full_lifecycle_to_victory_on_real_pg(reset_db_pool: str) -> None:
    """AC1: idle -> encounter_start -> initiative -> [declaration -> resolution -> wrap]* -> combat_end.
    A seeded encounter drives to victory on real PG; combat_instances is persisted at start and
    deleted at end, and XP is awarded."""
    pool = await db.get_pool()
    player_id = "cap_m41_lifecycle"
    await _seed_armed_player(pool, player_id)

    ctx = make_context(player_id)
    raw = await combat_init._start_combat_impl(ctx, "hollow_wisp", "A hollow wisp coalesces from the murk.")
    assert isinstance(raw, tuple), "a hostile encounter hands off (combat agent, json)"

    cs = ctx.userdata.combat_state
    assert cs is not None and cs.beat == "declaration"
    combat_id = cs.combat_id
    # encounter_start persisted the combat_instances row.
    assert await pool.fetchrow("SELECT 1 FROM combat_instances WHERE combat_id = $1", combat_id) is not None
    enemy = next(p for p in cs.participants if p.type == "enemy")
    enemy_action = enemy.action_pool[0]["name"]

    # Drive the loop to victory. hollow_wisp is 22 HP; 11/hit -> 2 rounds. The player (28 HP) survives
    # the wisp's <=2 symmetric hits regardless of initiative order.
    result: str | tuple = ""
    for _ in range(6):  # safety bound; expect 2 rounds
        decls = {
            player_id: {"type": "attack", "action": "Longsword", "target_id": enemy.id},
            enemy.id: {"type": "attack", "action": enemy_action, "target_id": player_id},
        }
        await combat_turn._declare_phase_impl(ctx, decls)
        result = await combat_turn._resolve_phase_impl(ctx, resolver=_damage_resolver(11))
        if isinstance(result, tuple):
            break

    assert isinstance(result, tuple), "the winning wrap fires end_combat and hands back"
    _agent, json_str = result
    payload = json.loads(json_str)
    assert payload["outcome"] == "victory"
    assert payload["xp_total"] > 0  # the fallen wisp's xp_value was awarded
    # combat_end cleared the in-memory state and deleted the combat_instances SSOT row.
    assert ctx.userdata.combat_state is None
    assert await pool.fetchrow("SELECT 1 FROM combat_instances WHERE combat_id = $1", combat_id) is None


async def test_save_and_reload_resumes_mid_phase(reset_db_pool: str) -> None:
    """AC2: a combat paused mid-phase, saved and reloaded, resumes advance_combat_phase from the
    saved beat with identical pending_declarations."""
    pool = await db.get_pool()
    combat_id = "combat_cap_m41_resume"
    original = _resolution_state(player_hp=20, enemy_hp=7)  # RESOLUTION beat, pending_declarations populated
    original.combat_id = combat_id

    try:
        await db_mutations.save_combat_state(combat_id, original.to_dict(), conn=pool)
        loaded = await db_mutations.load_combat_state(combat_id, conn=pool)

        assert loaded is not None
        assert loaded.beat == "resolution"
        assert loaded.pending_declarations == original.pending_declarations
        # Resume: advancing the reloaded state resolves the saved declarations into packets — proof
        # the phase picks up exactly where it was persisted, not from a fresh declaration beat.
        _next, adv = combat_phase.advance_combat_phase(loaded)
        assert [p.actor_id for p in adv.packets] == [
            p.actor_id for p in combat_phase.advance_combat_phase(original)[1].packets
        ]
        assert len(adv.packets) == len(original.pending_declarations)
    finally:
        await db_mutations.delete_combat_state(combat_id, conn=pool)


def _crit_resolver():
    """A resolve_attack mock that lands a non-lethal critical (damage 1 so the enemy survives and the
    phase loops, exposing the packet summaries) with critical_success=True."""

    def _resolve(attacker_data, action, target_ac, target_hp):
        return AttackResult(
            hit=True,
            roll=20,
            attack_modifier=3,
            attack_total=23,
            target_ac=target_ac,
            damage=1,
            damage_type="slashing",
            critical_success=True,
            critical_failure=False,
            target_hp_remaining=max(0, target_hp - 1),
            target_killed=False,
            narrative_hint="A critical strike!",
        )

    r = MagicMock()
    r.resolve_attack = MagicMock(side_effect=_resolve)
    return r


async def test_resolution_packets_carry_dramatic_and_crit_flags(reset_db_pool: str) -> None:
    """AC3: resolution-beat packets each carry a dramatic-flag field, and the resolve summaries carry
    critical flags consistent with the AttackResult (post story-008)."""
    # Dramatic flag: the engine's Beat-2 packets carry the placeholder (filled by M4.5).
    _next, adv = combat_phase.advance_combat_phase(_resolution_state())
    assert adv.packets
    for packet in adv.packets:
        assert hasattr(packet, "dramatic")
        assert packet.dramatic is False  # M4.1 placeholder default

    # Crit flag: a non-lethal crit loops the phase; every resolved summary propagates critical=True.
    pool = await db.get_pool()
    player_id = "cap_m41_crit"
    await _seed_armed_player(pool, player_id)
    ctx = make_context(player_id)
    raw = await combat_init._start_combat_impl(ctx, "hollow_wisp", "A wisp flickers.")
    assert isinstance(raw, tuple)
    cs = ctx.userdata.combat_state
    enemy = next(p for p in cs.participants if p.type == "enemy")
    combat_id = cs.combat_id

    try:
        await combat_turn._declare_phase_impl(
            ctx,
            {
                player_id: {"type": "attack", "action": "Longsword", "target_id": enemy.id},
                enemy.id: {"type": "attack", "action": enemy.action_pool[0]["name"], "target_id": player_id},
            },
        )
        result = await combat_turn._resolve_phase_impl(ctx, resolver=_crit_resolver())
        assert isinstance(result, str), "a non-lethal crit loops the phase rather than ending it"
        packets = json.loads(result)["packets"]
        resolved = [p for p in packets if p.get("resolved")]
        assert resolved and all(p["critical"] is True for p in resolved)
    finally:
        await db_mutations.delete_combat_state(combat_id, conn=pool)
