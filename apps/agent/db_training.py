"""Training activity DB queries and mutations. Separate module to avoid deepening db_queries.py."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import asyncpg

import db

if TYPE_CHECKING:
    from training_rules import TrainingActivityType, TrainingState

logger = logging.getLogger("divineruin.db_training")

_COLUMNS = "id, player_id, activity_type, state, data, transition_at, created_at, updated_at"


def _to_dict(row: asyncpg.Record) -> dict:
    r = dict(row)
    # No JSONB codec is registered on the pool, so asyncpg hands back the
    # `data` column as a raw JSON string. Deserialize here so every consumer
    # (e.g. async_worker.advance_training_cycles) gets a real dict to index.
    raw = row["data"]
    r["data"] = json.loads(raw) if isinstance(raw, str) else raw
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
          AND transition_at <= NOW()
        ORDER BY transition_at
        """
    )
    return [_to_dict(row) for row in rows]


async def create_training_activity(
    player_id: str,
    activity_type: TrainingActivityType,
    state: TrainingState,
    data: dict,
    *,
    transition_at: datetime | None = None,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> str:
    _conn = conn or await db.get_pool()
    activity_id = f"train_{uuid.uuid4().hex[:12]}"
    await _conn.execute(
        """
        INSERT INTO training_activities (id, player_id, activity_type, state, data, transition_at)
        VALUES ($1, $2, $3, $4, $5::jsonb, $6)
        """,
        activity_id,
        player_id,
        activity_type,
        state,
        json.dumps(data),
        transition_at,
    )
    return activity_id


async def claim_training_accrual(
    activity_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> bool:
    """Atomically claim an activity's completion accrual; True iff freshly claimed.

    Idempotency ledger for the worker's second-half accrual (debt b20815f92023):
    the first call for an activity_id inserts a row and returns True (apply the
    accrual); a retry of the same activity_id conflicts and returns False (skip).
    Used by apply_skill_practice_advancement, whose shared skill-counter increment
    has no per-cycle progress row to guard with last_activity_id (unlike the spell
    and mentor-variant tracks).
    """
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow(
        """
        INSERT INTO training_cycle_accruals (activity_id) VALUES ($1)
        ON CONFLICT (activity_id) DO NOTHING
        RETURNING activity_id
        """,
        activity_id,
    )
    return row is not None


async def update_training_activity(
    activity_id: str,
    state: TrainingState,
    data_updates: dict,
    *,
    transition_at: datetime | None = None,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    _conn = conn or await db.get_pool()
    if transition_at is None:
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
    else:
        await _conn.execute(
            """
            UPDATE training_activities
            SET state = $2,
                data = data || $3::jsonb,
                transition_at = $4,
                updated_at = NOW()
            WHERE id = $1
            """,
            activity_id,
            state,
            json.dumps(data_updates),
            transition_at,
        )
