"""DB persistence for the M9 mentor-variant training loop (story-002).

Holds the reads + writes for the per-character unlocked set
(character_mentor_variants) and the in-flight multi-session loop
(mentor_variant_learning_progress) — the tables from migration 036. Mirrors
character_spells.py: every function takes an optional conn= (Connection or Pool)
and falls back to the singleton pool, using single-statement ON CONFLICT upserts.

A variant mid-training lives only in mentor_variant_learning_progress and is NOT
unlocked until the worker promotes it (record_unlocked + delete_learning_progress
on completion — async_worker_training drives it). learn(variant) seeds the
progress row at cycles_completed=0; each completed session advances one cycle.

last_activity_id makes cycle accrual idempotent under a worker retry (debt
b20815f92023): advance_learning_cycle increments only for a NEW activity id, so a
retry after a narration-LLM failure re-runs as a no-op.
"""

import asyncpg

import db
import db_training

# The only acquisition track for a mentor variant — there is no instant track
# (variants must be trained over a multi-session mentor loop).
_ACQUISITION_TRACK = "mentor_training"


async def seed_progress(
    player_id: str,
    variant_id: str,
    cycles_required: int,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Create the in-flight progress row at cycles_completed=0 (idempotent).

    Called by learn(variant) to start the loop before any session completes. ON
    CONFLICT DO NOTHING — re-invoking learn(variant) mid-training does not reset
    accrued cycles.
    """
    if cycles_required < 1:
        raise ValueError(f"cycles_required must be >= 1, got {cycles_required}")
    _conn = conn or await db.get_pool()
    await _conn.execute(
        """
        INSERT INTO mentor_variant_learning_progress (player_id, variant_id, cycles_completed, cycles_required)
        VALUES ($1, $2, 0, $3)
        ON CONFLICT (player_id, variant_id) DO NOTHING
        """,
        player_id,
        variant_id,
        cycles_required,
    )


async def advance_learning_cycle(
    player_id: str,
    variant_id: str,
    cycles_required: int,
    *,
    activity_id: str | None = None,
    midpoint_decision_id: str | None = None,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> dict:
    """Record one completed training cycle toward a mentor variant.

    Upserts the in-flight mentor_variant_learning_progress row (cycles_completed +=
    1) and returns {cycles_completed, cycles_required, completed,
    midpoint_decision_id}. Does NOT unlock the variant; the caller promotes via
    record_unlocked + delete_learning_progress when `completed` is True, carrying
    midpoint_decision_id onto the unlocked variant.

    Idempotency (debt b20815f92023): when the caller passes the completing
    activity's `activity_id`, a repeated call with the SAME id (a worker retry
    after a narration failure) re-runs as a no-op — the increment is gated on the
    id differing from the stored last_activity_id. Mirrors
    character_spells.advance_learning_cycle.
    """
    return await db_training.upsert_learning_cycle(
        "mentor_variant_learning_progress",
        player_id,
        variant_id,
        cycles_required,
        midpoint_decision_id=midpoint_decision_id,
        activity_id=activity_id,
        conn=conn,
    )


async def record_unlocked(
    player_id: str,
    variant_id: str,
    *,
    midpoint_decision_id: str | None = None,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Add an unlocked variant to the character's set (idempotent).

    ON CONFLICT DO NOTHING — re-unlocking is a no-op. acquisition_track is always
    'mentor_training' (variants have no instant track); midpoint_decision_id
    carries the training choice onto the unlocked variant.
    """
    _conn = conn or await db.get_pool()
    await _conn.execute(
        """
        INSERT INTO character_mentor_variants (player_id, variant_id, acquisition_track, midpoint_decision_id)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (player_id, variant_id) DO NOTHING
        """,
        player_id,
        variant_id,
        _ACQUISITION_TRACK,
        midpoint_decision_id,
    )


async def get_learning_progress(
    player_id: str,
    variant_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> dict | None:
    """Return the in-flight learning row for a variant, or None if none in progress."""
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow(
        "SELECT cycles_completed, cycles_required, midpoint_decision_id "
        "FROM mentor_variant_learning_progress WHERE player_id = $1 AND variant_id = $2",
        player_id,
        variant_id,
    )
    if row is None:
        return None
    return {
        "cycles_completed": row["cycles_completed"],
        "cycles_required": row["cycles_required"],
        "midpoint_decision_id": row["midpoint_decision_id"],
    }


async def delete_learning_progress(
    player_id: str,
    variant_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Clear an in-flight learning row (after promotion to the unlocked set)."""
    _conn = conn or await db.get_pool()
    await _conn.execute(
        "DELETE FROM mentor_variant_learning_progress WHERE player_id = $1 AND variant_id = $2",
        player_id,
        variant_id,
    )


async def is_unlocked(
    player_id: str,
    variant_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> bool:
    """True if the player has unlocked this variant."""
    _conn = conn or await db.get_pool()
    return bool(
        await _conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM character_mentor_variants WHERE player_id = $1 AND variant_id = $2)",
            player_id,
            variant_id,
        )
    )


async def get_unlocked(
    player_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> list[dict]:
    """Return the character's unlocked variants (the set)."""
    _conn = conn or await db.get_pool()
    rows = await _conn.fetch(
        "SELECT variant_id, acquisition_track, midpoint_decision_id FROM character_mentor_variants WHERE player_id = $1",
        player_id,
    )
    return [
        {
            "variant_id": r["variant_id"],
            "acquisition_track": r["acquisition_track"],
            "midpoint_decision_id": r["midpoint_decision_id"],
        }
        for r in rows
    ]
