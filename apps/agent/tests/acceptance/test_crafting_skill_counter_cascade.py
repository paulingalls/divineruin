"""Real-DB acceptance proofs for the hidden Crafting skill counter (story-006).

Migration 026 creates player_crafting_skill_counter with player_id -> players
ON DELETE CASCADE (decision 63c0372460d7), so deleting a player removes their
counter row instead of orphaning it (AC#3). The testcontainer harness replays
every scripts/migrations/*.sql in order, so this exercises 026 against the real
schema. The round-trip test proves the atomic +1 UPSERT in
db_mutations.increment_crafting_skill_counter — the part the unit tests mock.
Runs under REQUIRE_DOCKER; skips clean when Docker is down.
"""

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
    """Two crafting Failures take the counter 0 -> 1 -> 2 (atomic +1 UPSERT, real DB)."""
    pool = await db.get_pool()
    player_id = "player_counter_rt"
    await _insert_player(pool, player_id)

    assert await db_queries.get_crafting_skill_counter(player_id) == 0
    await db_mutations.increment_crafting_skill_counter(player_id)
    assert await db_queries.get_crafting_skill_counter(player_id) == 1
    await db_mutations.increment_crafting_skill_counter(player_id)
    assert await db_queries.get_crafting_skill_counter(player_id) == 2


async def test_deleting_player_cascades_to_counter(reset_db_pool: str) -> None:
    """AC#3: deleting a player cascade-removes their crafting-counter row (no orphan)."""
    pool = await db.get_pool()
    player_id = "player_counter_cascade"
    await _insert_player(pool, player_id)
    await db_mutations.increment_crafting_skill_counter(player_id)

    count_sql = "SELECT COUNT(*) FROM player_crafting_skill_counter WHERE player_id = $1"
    assert await pool.fetchval(count_sql, player_id) == 1

    await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)

    assert await pool.fetchval(count_sql, player_id) == 0
