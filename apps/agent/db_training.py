"""Training activity DB queries and mutations. Separate module to avoid deepening db_queries.py."""

import json
import logging
import uuid
from typing import TYPE_CHECKING

import asyncpg

import db

if TYPE_CHECKING:
    from training_rules import TrainingActivityType, TrainingState

logger = logging.getLogger("divineruin.db_training")

_COLUMNS = "id, player_id, activity_type, state, data, created_at, updated_at"


def _to_dict(row: asyncpg.Record) -> dict:
    r = dict(row)
    r["data"] = row["data"]  # asyncpg returns JSONB as dict
    return r


async def get_training_activity(
    activity_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
    for_update: bool = False,
) -> dict | None:
    _conn = conn or await db.get_pool()
    suffix = " FOR UPDATE" if for_update else ""
    row = await _conn.fetchrow(
        f"SELECT {_COLUMNS} FROM training_activities WHERE id = $1{suffix}",
        activity_id,
    )
    if row is None:
        return None
    return _to_dict(row)


async def get_player_training_activities(
    player_id: str,
    state: TrainingState | None = None,
    *,
    limit: int = 50,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> list[dict]:
    _conn = conn or await db.get_pool()
    if state:
        rows = await _conn.fetch(
            f"SELECT {_COLUMNS} FROM training_activities WHERE player_id = $1 AND state = $2 ORDER BY created_at LIMIT $3",
            player_id,
            state,
            limit,
        )
    else:
        rows = await _conn.fetch(
            f"SELECT {_COLUMNS} FROM training_activities WHERE player_id = $1 ORDER BY created_at LIMIT $2",
            player_id,
            limit,
        )
    return [_to_dict(row) for row in rows]


async def get_due_training_transitions(
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> list[dict]:
    """Find training activities whose transition_at has passed and need state advancement."""
    _conn = conn or await db.get_pool()
    rows = await _conn.fetch(
        f"""
        SELECT {_COLUMNS}
        FROM training_activities
        WHERE state IN ('running_first_half', 'running_second_half')
          AND (data->>'transition_at')::timestamptz <= NOW()
        ORDER BY (data->>'transition_at')::timestamptz
        """
    )
    return [_to_dict(row) for row in rows]


async def create_training_activity(
    player_id: str,
    activity_type: TrainingActivityType,
    state: TrainingState,
    data: dict,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> str:
    _conn = conn or await db.get_pool()
    activity_id = f"train_{uuid.uuid4().hex[:12]}"
    await _conn.execute(
        """
        INSERT INTO training_activities (id, player_id, activity_type, state, data)
        VALUES ($1, $2, $3, $4, $5::jsonb)
        """,
        activity_id,
        player_id,
        activity_type,
        state,
        json.dumps(data),
    )
    return activity_id


async def update_training_activity(
    activity_id: str,
    state: TrainingState,
    data_updates: dict,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    _conn = conn or await db.get_pool()
    await _conn.execute(
        """
        UPDATE training_activities
        SET state = $2,
            data = data || $3::jsonb,
            updated_at = NOW()
        WHERE id = $1
        """,
        activity_id,
        state,
        json.dumps(data_updates),
    )
