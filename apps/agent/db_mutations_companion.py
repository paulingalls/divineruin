"""DB persistence for per-player companion relationship state (M6.4, story-003).

Its own module (db_mutations.py sits at the 500-line cap) keeps the companion writers
cohesive — same call as db_mutations_reputation / db_mutations_gathering. All three write
companion_relationships (migration 042 + 043), whose authoritative inputs are session_count
and affinity; relationship_tier is a denormalized cache of the effective rank that only
external readers (HUD, debugging) consult. Accepts conn= for transaction participation.

The read side lives in db_queries.get_companion_relationship; the tier math in
companion_relationship.py; the orchestration in companion_relationship_queries.py.
"""

import json

import asyncpg

import db


async def upsert_companion_relationship(
    player_id: str,
    companion_id: str,
    *,
    relationship_tier: int,
    session_count: int,
    affinity: int,
    session_memories: list[str],
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Upsert companion relationship state (M6.4 / story-003, HYBRID model).

    relationship_tier is a denormalized cache of the effective rank for external/inspection
    readers (e.g. HUD, debugging) — the agent NEVER reads it back; every consumer re-derives the
    rank from the authoritative session_count + affinity. ON CONFLICT keeps the write atomic,
    mirroring set_npc_disposition. Callers in a FOR UPDATE lock pass their conn.
    """
    _conn = conn or await db.get_pool()
    memories = json.dumps(session_memories)
    await _conn.execute(
        """
        INSERT INTO companion_relationships
            (player_id, companion_id, relationship_tier, session_count, affinity, session_memories)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb)
        ON CONFLICT (player_id, companion_id)
        DO UPDATE SET
            relationship_tier = $3,
            session_count = $4,
            affinity = $5,
            session_memories = $6::jsonb
        """,
        player_id,
        companion_id,
        relationship_tier,
        session_count,
        affinity,
        memories,
    )


async def bump_companion_affinity(
    player_id: str,
    companion_id: str,
    delta: int,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> tuple[int, int] | None:
    """Atomically accumulate `delta` into affinity (clamped >= 0); return (new_affinity,
    session_count).

    Single read-modify-write UPDATE so two concurrent errand resolutions for the same companion
    cannot lose an increment (the worker path runs lock-free). Touches only affinity — session_count
    is RETURNed (unchanged) so the caller can recompute the denormalized relationship_tier cache
    without a second read. Returns None if the companion has no row yet (never-met → nothing to
    nudge).
    """
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow(
        """
        UPDATE companion_relationships
        SET affinity = GREATEST(0, affinity + $3)
        WHERE player_id = $1 AND companion_id = $2
        RETURNING affinity, session_count
        """,
        player_id,
        companion_id,
        delta,
    )
    return (row["affinity"], row["session_count"]) if row is not None else None


async def cache_companion_tier(
    player_id: str,
    companion_id: str,
    relationship_tier: int,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Refresh the denormalized relationship_tier cache (external readers only; agent re-derives).

    Best-effort: a no-op when the row is absent. Kept separate from bump_companion_affinity so the
    authoritative affinity bump stays a single atomic statement.
    """
    _conn = conn or await db.get_pool()
    await _conn.execute(
        """
        UPDATE companion_relationships
        SET relationship_tier = $3
        WHERE player_id = $1 AND companion_id = $2
        """,
        player_id,
        companion_id,
        relationship_tier,
    )
