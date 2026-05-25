"""Real-DB acceptance proof for the systemic player CASCADE-FK backfill (migration 021).

Migrations 008 + 020 added players(player_id) ON DELETE CASCADE FKs to a few
per-player tables, but ten more added since lacked it, so deleting a player
orphaned their rows (debt ac2ad5230209). Migration 021 backfills the FK on all
ten. The testcontainer harness replays every scripts/migrations/*.sql in order,
so this exercises 021 against the real schema: without it, the DELETE leaves
orphan rows and the assertion fails (genuine TDD red). Runs under REQUIRE_DOCKER;
skips clean when Docker is down.
"""

from __future__ import annotations

import db

# table -> INSERT (columns) VALUES clause seeding one row for `player_id` ($1).
# Every NOT NULL column the table requires (beyond defaults) is supplied.
_SEED_ROWS: dict[str, str] = {
    "player_inventory": "(player_id, item_id, data) VALUES ($1, 'oak_wood', '{}'::jsonb)",
    "player_quests": "(player_id, quest_id, data) VALUES ($1, 'q1', '{}'::jsonb)",
    "player_reputation": "(player_id, faction_id, data) VALUES ($1, 'accord', '{}'::jsonb)",
    "npc_dispositions": "(npc_id, player_id, data) VALUES ('npc1', $1, '{}'::jsonb)",
    "session_summaries": "(player_id, session_id, data) VALUES ($1, 's1', '{}'::jsonb)",
    "player_map_progress": "(player_id, location_id, data) VALUES ($1, 'loc1', '{}'::jsonb)",
    "god_whispers": "(id, player_id, data) VALUES ('w1', $1, '{}'::jsonb)",
    "story_moments": (
        "(id, session_id, player_id, moment_key, description, template_id) VALUES ('m1', 's1', $1, 'k1', 'desc', 't1')"
    ),
    "skill_advancement": "(player_id, skill_id) VALUES ($1, 'crafting')",
    "training_activities": "(id, player_id, activity_type, state) VALUES ('t1', $1, 'technique_base', 'initiated')",
}


async def _row_count(pool, table: str, player_id: str) -> int:
    return await pool.fetchval(f"SELECT COUNT(*) FROM {table} WHERE player_id = $1", player_id)


async def test_deleting_player_cascades_to_all_backfilled_tables(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    player_id = "player_fk_backfill"
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, '{}'::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data = '{}'::jsonb",
        player_id,
    )

    for table, clause in _SEED_ROWS.items():
        await pool.execute(f"INSERT INTO {table} {clause}", player_id)
        assert await _row_count(pool, table, player_id) == 1, f"seed failed for {table}"

    # Deleting the player must cascade-remove every per-player row (no orphans).
    await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)

    for table in _SEED_ROWS:
        assert await _row_count(pool, table, player_id) == 0, f"{table} orphaned rows after player delete"
