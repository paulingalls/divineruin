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


async def prune_training_cycle_accruals(
    *,
    retention_days: int = 7,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> int:
    """Delete idempotency-ledger rows older than the retention window; return rows deleted.

    Bounds the otherwise-unbounded training_cycle_accruals ledger (debt 8336cc9c9d03). The
    worker calls this every maintenance cycle. A row only guards against re-applying an
    activity's accrual while that activity could still be retried by the worker — bounded by
    its resolving_at timeout (minutes/hours) — so any row older than retention_days can be
    deleted with no risk of a double-apply. The 7-day default assumes no activity stays
    retryable for longer; widen it if that ceases to hold.
    """
    _conn = conn or await db.get_pool()
    status = await _conn.execute(
        "DELETE FROM training_cycle_accruals WHERE applied_at < NOW() - make_interval(days => $1)",
        retention_days,
    )
    # asyncpg returns a command tag like "DELETE 5"; the trailing token is the row count.
    return int(status.split()[-1])


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


# Per-cycle learning-progress tables share one upsert engine; they differ only in the
# table name and its entity column. Whitelisting table -> entity column here is the
# single source of that mapping AND keeps the f-string interpolation injection-safe
# (asyncpg cannot parameterize identifiers).
_LEARNING_PROGRESS_TABLES = {
    "spell_learning_progress": "spell_id",
    "mentor_variant_learning_progress": "variant_id",
}


async def upsert_learning_cycle(
    table: str,
    player_id: str,
    entity_id: str,
    cycles_required: int,
    *,
    midpoint_decision_id: str | None = None,
    activity_id: str | None = None,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> dict:
    """Record one completed training cycle in a *_learning_progress table.

    The shared engine behind character_spells.advance_learning_cycle and
    mentor_variant_progress.advance_learning_cycle (concern 5d7feeae22ae): the two
    tracks differ only in table + entity column (whitelisted in
    _LEARNING_PROGRESS_TABLES). Increments cycles_completed by 1 and returns
    {cycles_completed, cycles_required, completed, midpoint_decision_id}; COALESCE
    keeps the first midpoint_decision_id.

    Idempotency (debt b20815f92023): when the caller passes the completing activity's
    `activity_id`, a repeated call with the SAME id (a worker retry after a narration
    failure) re-runs as a no-op — the increment is gated on the id differing from the
    stored last_activity_id. With activity_id=None the increment is unconditional.
    """
    entity_col = _LEARNING_PROGRESS_TABLES.get(table)
    if entity_col is None:
        raise ValueError(f"unknown learning-progress table {table!r}")
    if cycles_required < 1:
        # Fail loud: a tier needs >=1 cycle; 0 completes on the first cycle, negative
        # makes completion unreachable.
        raise ValueError(f"cycles_required must be >= 1, got {cycles_required}")
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow(
        f"""
        INSERT INTO {table}
            (player_id, {entity_col}, cycles_completed, cycles_required, midpoint_decision_id, last_activity_id)
        VALUES ($1, $2, 1, $3, $4, $5)
        ON CONFLICT (player_id, {entity_col}) DO UPDATE SET
            cycles_completed = {table}.cycles_completed
                + CASE WHEN $5::text IS NOT NULL
                        AND {table}.last_activity_id IS NOT DISTINCT FROM $5::text
                       THEN 0 ELSE 1 END,
            midpoint_decision_id = COALESCE($4, {table}.midpoint_decision_id),
            last_activity_id = $5
        RETURNING cycles_completed, cycles_required, midpoint_decision_id
        """,
        player_id,
        entity_id,
        cycles_required,
        midpoint_decision_id,
        activity_id,
    )
    if row is None:  # an upsert with RETURNING always yields a row — fail loud if not
        raise RuntimeError(f"{table} upsert returned no row for {entity_id!r}")
    return {
        "cycles_completed": row["cycles_completed"],
        "cycles_required": row["cycles_required"],
        "completed": row["cycles_completed"] >= row["cycles_required"],
        "midpoint_decision_id": row["midpoint_decision_id"],
    }
