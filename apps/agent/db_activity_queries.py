"""Activity, divine favor, narrative, and player-existence queries.

State queries that take an optional conn parameter for transaction support.
"""

import json
import logging

import asyncpg

import db

logger = logging.getLogger("divineruin.db")


async def get_player_activities(
    player_id: str, status: str | None = None, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> list[dict]:
    """Get all activities for a player, optionally filtered by status."""
    _conn = conn or await db.get_pool()
    if status:
        rows = await _conn.fetch(
            "SELECT id, data FROM async_activities WHERE player_id = $1 AND data->>'status' = $2 ORDER BY created_at DESC",
            player_id,
            status,
        )
    else:
        rows = await _conn.fetch(
            "SELECT id, data FROM async_activities WHERE player_id = $1 ORDER BY created_at DESC",
            player_id,
        )
    return [{"id": row["id"], **json.loads(row["data"])} for row in rows]


async def get_activity(
    activity_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None, for_update: bool = False
) -> dict | None:
    """Get a single activity by ID."""
    _conn = conn or await db.get_pool()
    sql_query = "SELECT id, player_id, data FROM async_activities WHERE id = $1"
    if for_update:
        sql_query += " FOR UPDATE"
    row = await _conn.fetchrow(sql_query, activity_id)
    if row is None:
        return None
    return {"id": row["id"], "player_id": row["player_id"], **json.loads(row["data"])}


async def get_due_activities(*, conn: asyncpg.Connection | asyncpg.Pool | None = None) -> list[dict]:
    """Find activities where resolve_at <= NOW() and status is 'in_progress'."""
    _conn = conn or await db.get_pool()
    rows = await _conn.fetch(
        """
        SELECT id, player_id, data FROM async_activities
        WHERE data->>'status' = 'in_progress'
          AND (data->>'resolve_at')::timestamptz <= NOW()
        ORDER BY (data->>'resolve_at')::timestamptz ASC
        """,
    )
    return [{"id": row["id"], "player_id": row["player_id"], **json.loads(row["data"])} for row in rows]


async def count_active_by_slot(
    player_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> dict[str, int]:
    """Count active activities per slot: training, crafting, companion."""
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow(
        """
        SELECT
            COALESCE(SUM(CASE WHEN src = 'training' THEN 1 ELSE 0 END), 0) AS training,
            COALESCE(SUM(CASE WHEN src = 'crafting' THEN 1 ELSE 0 END), 0) AS crafting,
            COALESCE(SUM(CASE WHEN src = 'companion_errand' THEN 1 ELSE 0 END), 0) AS companion
        FROM (
            SELECT data->>'activity_type' AS src
            FROM async_activities
            WHERE player_id = $1 AND data->>'status' = 'in_progress'
          UNION ALL
            SELECT 'training' AS src
            FROM training_activities
            WHERE player_id = $1 AND state != 'complete'
        ) combined
        """,
        player_id,
    )
    return {
        "training": row["training"] if row else 0,
        "crafting": row["crafting"] if row else 0,
        "companion": row["companion"] if row else 0,
    }


async def player_exists(player_id: str) -> bool:
    """Check if player row exists without loading full data."""
    pool = await db.get_pool()
    row = await pool.fetchrow(
        "SELECT 1 FROM players WHERE player_id = $1",
        player_id,
    )
    return row is not None


async def get_divine_favor(player_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None) -> dict | None:
    """Read divine_favor from player JSONB data."""
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow(
        "SELECT data->'divine_favor' AS favor FROM players WHERE player_id = $1",
        player_id,
    )
    if row is None or row["favor"] is None:
        return None
    return json.loads(row["favor"])


async def get_pending_god_whispers(player_id: str) -> list[dict]:
    """Return all pending god whispers for a player."""
    pool = await db.get_pool()
    rows = await pool.fetch(
        """
        SELECT id, data FROM god_whispers
        WHERE player_id = $1 AND data->>'status' = 'pending'
        ORDER BY created_at DESC
        """,
        player_id,
    )
    return [{"id": row["id"], **json.loads(row["data"])} for row in rows]


async def get_session_story_moments(
    session_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> list[dict]:
    """Return all story moments for a session, ordered by creation time."""
    _conn = conn or await db.get_pool()
    rows = await _conn.fetch(
        """
        SELECT moment_key, description, template_id, asset_id
        FROM story_moments
        WHERE session_id = $1
        ORDER BY created_at ASC
        """,
        session_id,
    )
    return [
        {
            "moment_key": row["moment_key"],
            "description": row["description"],
            "template_id": row["template_id"],
            "asset_id": row["asset_id"],
        }
        for row in rows
    ]


async def count_session_story_moments(session_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None) -> int:
    """Count story moments in a session."""
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow(
        "SELECT COUNT(*) AS cnt FROM story_moments WHERE session_id = $1",
        session_id,
    )
    return row["cnt"] if row else 0


async def get_player_map_progress(player_id: str) -> list[dict]:
    """Return all visited locations for a player."""
    pool = await db.get_pool()
    rows = await pool.fetch(
        "SELECT location_id, data FROM player_map_progress WHERE player_id = $1",
        player_id,
    )
    return [
        {
            "location_id": row["location_id"],
            "connections": json.loads(row["data"]).get("connections", []),
        }
        for row in rows
    ]
