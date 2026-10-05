"""Execute the known-recipe cascade against the real schema."""

from __future__ import annotations

import db


async def _known_recipe_count(pool, player_id: str) -> int:
    return await pool.fetchval("SELECT COUNT(*) FROM player_known_recipes WHERE player_id = $1", player_id)


async def test_deleting_player_cascades_to_known_recipes(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    player_id = "player_cascade"
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
        player_id,
        "{}",
    )
    await pool.execute(
        "INSERT INTO player_known_recipes (player_id, recipe_id, learned_via) "
        "VALUES ($1, $2, $3) ON CONFLICT (player_id, recipe_id) DO NOTHING",
        player_id,
        "iron_sword",
        "npc_teaching",
    )
    assert await _known_recipe_count(pool, player_id) == 1

    # Deleting the player must cascade-remove their known-recipe rows (no orphans).
    await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)

    assert await _known_recipe_count(pool, player_id) == 0
