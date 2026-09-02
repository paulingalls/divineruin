"""DB persistence for the skill_advancement table (M1.2 hybrid counter).

Its own module (db_mutations.py sits at the 500-line cap) keeps the three writers of one
table together — same call as db_mutations_reputation / db_mutations_gathering. tier +
use_counter carry the hybrid advancement contract; narrative_moment_ready is the
Expert->Master gate, set by the DM tool and cleared when the advancement lands.

The pure advancement math is check_resolution.record_skill_use; the orchestration that
pairs a read with these writes is skill_persistence.py.
"""

import asyncpg

import db


async def update_skill_advancement(
    player_id: str,
    skill: str,
    tier: str,
    use_counter: int,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Upsert skill advancement record."""
    _conn = conn or await db.get_pool()
    await _conn.execute(
        """
        INSERT INTO skill_advancement (player_id, skill_id, tier, use_counter, updated_at)
        VALUES ($1, $2, $3, $4, NOW())
        ON CONFLICT (player_id, skill_id)
        DO UPDATE SET tier = $3, use_counter = $4, updated_at = NOW()
        """,
        player_id,
        skill,
        tier,
        use_counter,
    )


async def mark_narrative_moment(
    player_id: str, skill: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> None:
    """Set narrative_moment_ready flag for Expert→Master advancement."""
    _conn = conn or await db.get_pool()
    await _conn.execute(
        """
        INSERT INTO skill_advancement (player_id, skill_id, narrative_moment_ready, updated_at)
        VALUES ($1, $2, TRUE, NOW())
        ON CONFLICT (player_id, skill_id)
        DO UPDATE SET narrative_moment_ready = TRUE, updated_at = NOW()
        """,
        player_id,
        skill,
    )


async def clear_narrative_moment(
    player_id: str, skill: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> None:
    """Clear narrative_moment_ready flag after Expert→Master advancement."""
    _conn = conn or await db.get_pool()
    await _conn.execute(
        """
        UPDATE skill_advancement SET narrative_moment_ready = FALSE, updated_at = NOW()
        WHERE player_id = $1 AND skill_id = $2
        """,
        player_id,
        skill,
    )
