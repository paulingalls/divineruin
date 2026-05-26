"""Persistence for player_failed_experiments (M5.3 experimentation).

A focused module for the new per-player table's read + write. db_mutations.py is over the
500-line cap (debt 1f235ab5066a) and the split-on-touch convention would force a
disproportionate split, so this new persistence lives here instead. The known-recipe write
on a successful experiment still reuses db_mutations.add_player_known_recipe.
"""

import asyncpg

import db


async def record_failed_experiment(
    player_id: str,
    intended_output: str,
    material_combination: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Record a no-match experiment combo so it isn't fruitlessly retried. Idempotent."""
    _conn = conn or await db.get_pool()
    await _conn.execute(
        """
        INSERT INTO player_failed_experiments (player_id, intended_output, material_combination)
        VALUES ($1, $2, $3)
        ON CONFLICT (player_id, intended_output, material_combination) DO NOTHING
        """,
        player_id,
        intended_output,
        material_combination,
    )


async def has_failed_experiment(
    player_id: str,
    intended_output: str,
    material_combination: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> bool:
    """True if this player has already recorded this no-match combination."""
    _conn = conn or await db.get_pool()
    found = await _conn.fetchval(
        """
        SELECT 1 FROM player_failed_experiments
        WHERE player_id = $1 AND intended_output = $2 AND material_combination = $3
        """,
        player_id,
        intended_output,
        material_combination,
    )
    return found is not None
