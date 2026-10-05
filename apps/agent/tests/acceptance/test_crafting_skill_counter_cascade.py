"""Execute the real cascade and atomic upsert; mock connections cannot certify either."""

from __future__ import annotations

import db
import db_mutations
import db_queries


async def _insert_player(pool, player_id: str) -> None:
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
        player_id,
        "{}",
    )


async def test_increment_accumulates_atomically(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    player_id = "player_counter_rt"
    await _insert_player(pool, player_id)

    assert await db_queries.get_crafting_skill_counter(player_id) == 0
    await db_mutations.increment_crafting_skill_counter(player_id)
    assert await db_queries.get_crafting_skill_counter(player_id) == 1
    await db_mutations.increment_crafting_skill_counter(player_id)
    assert await db_queries.get_crafting_skill_counter(player_id) == 2


async def test_deleting_player_cascades_to_counter(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    player_id = "player_counter_cascade"
    await _insert_player(pool, player_id)
    await db_mutations.increment_crafting_skill_counter(player_id)

    count_sql = "SELECT COUNT(*) FROM player_crafting_skill_counter WHERE player_id = $1"
    assert await pool.fetchval(count_sql, player_id) == 1

    await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)

    assert await pool.fetchval(count_sql, player_id) == 0
