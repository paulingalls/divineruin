"""Oversized weapon dice guarantee one-shot kills without mocking damage; large HP preserves the player through crossfire.
This observes the legendary budget, not a DM-driven legendary spend."""

from __future__ import annotations

import json
import random
from unittest.mock import patch

from acceptance._capstone_helpers import _d20, _resolve_round
from acceptance._catalog_cutover_helpers import cold_catalog_reads as cold_catalog_reads
from acceptance.seeds import seed_player
from sample_fixtures import make_context, make_mock_room

import combat_init
import combat_turn
import db
import db_mutations
import db_queries
import encounter_budget
import encounter_loot
from encounter_roles import _is_active_ability

_BIG_WEAPON = {"name": "Capstone Greatblade", "damage": "100d6", "damage_type": "slashing", "properties": []}

_ENCOUNTER = "cult_cell"
_BOSS_ID = "cult_leader"


async def _seed_capstone_player(pool, player_id: str) -> None:
    """Seed a player with the one-shot weapon (combat_init builds the action_pool from equipment
    entries carrying `damage`) and a huge HP pool so it survives the enemy crossfire to victory."""
    await seed_player(pool, player_id=player_id, location_id="accord_guild_hall")
    await pool.execute(
        "UPDATE players SET data = jsonb_set(jsonb_set(data, '{equipment}', $2::jsonb), '{hp}', $3::jsonb) "
        "WHERE player_id = $1",
        player_id,
        json.dumps({"main_hand": _BIG_WEAPON}),
        json.dumps({"current": 100_000, "max": 100_000}),
    )


def _by_id(cs, enemy_id: str):
    p = cs.get_participant(enemy_id)
    assert p is not None, f"{enemy_id} not in combat participants"
    return p


async def test_m47_init_derivation_budget_and_minion_floor(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    player_id = "cap_m47_init"
    await _seed_capstone_player(pool, player_id)

    ctx = make_context(player_id, room=make_mock_room())
    raw = await combat_init._start_combat_impl(ctx, _ENCOUNTER, "A cult cell turns, blades drawn.")
    assert isinstance(raw, tuple), "a hostile encounter hands off (combat agent, json)"

    cs = ctx.userdata.combat_state
    assert cs is not None and cs.beat == "declaration"
    assert await pool.fetchrow("SELECT 1 FROM combat_instances WHERE combat_id = $1", cs.combat_id) is not None

    minion = _by_id(cs, "cultist_1")
    assert minion.role == "minion"
    assert minion.hp_current == 5 and minion.hp_max == 5
    assert minion.attack_mod == 0 and minion.damage_mult == 0.75 and minion.dc_mod == -1
    assert minion.action_pool, "minion keeps its basic attack"
    assert all(not _is_active_ability(a) for a in minion.action_pool), "minion has no active abilities"

    # Standard (cult_fanatic): identity overlay.
    standard = _by_id(cs, "cult_fanatic_1")
    assert standard.role == "standard"
    assert standard.hp_current == 19
    assert standard.attack_mod == 0 and standard.damage_mult == 1.0 and standard.dc_mod == 0

    boss = _by_id(cs, _BOSS_ID)
    assert boss.role == "boss"
    assert boss.hp_current == 96 and boss.hp_max == 96
    assert boss.attack_mod == 2 and boss.damage_mult == 1.5 and boss.dc_mod == 2
    assert boss.legendary_actions == 1
    assert boss.signature_ability is not None

    # Encounter budget validates the role-tagged roster (informational flags, never gating).
    enemies = [{"role": p.role} for p in cs.participants if p.type == "enemy"]
    report = encounter_budget.calculate_encounter_budget(enemies, 2)
    assert report["too_many_bosses"] is False  # exactly one boss
    assert report["all_minion"] is False  # standards + boss anchor the minions
    for key in ("total", "level_band", "thresholds", "over_budget"):
        assert key in report

    # Minion drops no currency (D79), independent of category/tier.
    assert encounter_loot.calculate_currency_drop(minion.category, minion.tier, "minion", random.Random(0)) == 0

    await db_mutations.delete_combat_state(cs.combat_id, conn=pool)


async def test_m47_full_combat_to_victory_grants_role_scaled_rewards(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    player_id = "cap_m47_victory"
    await _seed_capstone_player(pool, player_id)

    ctx = make_context(player_id, room=make_mock_room())
    raw = await combat_init._start_combat_impl(ctx, _ENCOUNTER, "The cult cell closes in.")
    assert isinstance(raw, tuple)
    combat_id = ctx.userdata.combat_state.combat_id

    # Fell the non-boss enemies first so the boss is alive across rounds (its legendary budget is
    # observable while alive); the boss is the last target.
    non_boss = [p.id for p in ctx.userdata.combat_state.participants if p.type == "enemy" and p.id != _BOSS_ID]
    target_order = [*non_boss, _BOSS_ID]

    boss_legendary_through_rounds = False
    result: str | tuple = ""
    with patch("check_resolution.dice_roll", return_value=_d20(20)):  # every attack hits; damage is real
        for _ in range(20):
            cs = ctx.userdata.combat_state
            living = [p for p in cs.participants if p.type == "enemy" and not p.is_fallen]
            target = next(t for t in target_order if any(p.id == t and not p.is_fallen for p in cs.participants))
            decls = {player_id: {"type": "attack", "action": _BIG_WEAPON["name"], "target_id": target}}
            for e in living:
                decls[e.id] = {"type": "attack", "action": e.action_pool[0]["name"], "target_id": player_id}
            await combat_turn._declare_phase_impl(ctx, decls)
            result = await _resolve_round(ctx)
            if isinstance(result, tuple):
                break
            # Combat continues: the boss (felled last) carries its per-round legendary budget.
            boss = ctx.userdata.combat_state.get_participant(_BOSS_ID)
            if boss is not None and not boss.is_fallen and boss.legendary_actions == 1:
                boss_legendary_through_rounds = True

    assert isinstance(result, tuple), "the winning wrap fires end_combat and hands back"
    _agent, json_str = result
    payload = json.loads(json_str)
    assert payload["outcome"] == "victory"
    assert payload["xp_total"] == 425
    # humanoid standards + boss carry coin (minions add 0), so the pooled drop is positive (gold,
    # converted from the silver drop at the grant boundary — story-008).
    assert payload["currency_gold"] > 0
    assert boss_legendary_through_rounds, "the boss held a legendary action while alive across rounds"

    # Currency persisted to the player; the combat SSOT was cleared and deleted.
    player = await db_queries.get_player(player_id, conn=pool)
    assert (player or {}).get("gold", 0) >= payload["currency_gold"]
    assert ctx.userdata.combat_state is None
    assert await pool.fetchrow("SELECT 1 FROM combat_instances WHERE combat_id = $1", combat_id) is None
