"""CAS claim helpers for the async-activity 'resolving' transient state.

Closes the tool-vs-worker race in `_resolve_single_activity` by introducing a
`'resolving'` intermediate status that the worker atomically CAS-claims before
doing long-running LLM+TTS work outside the row lock. The tool path
(`errand_tools._resolve_companion_errand_impl`) raises ToolError when it sees
the resolving status, so one writer wins cleanly.

The three helpers:
- `claim_resolving`: CAS in_progress -> resolving, stamping resolving_at NOW().
- `revert_claim`: undo resolving -> in_progress for next-tick retry.
- `reset_stale_resolving`: tick-start recovery of crashed-worker rows whose
  resolving_at is older than `STALE_RESOLVING_THRESHOLD_SECONDS`.
"""

from __future__ import annotations

import json
import logging

import asyncpg

import db
from async_worker_config import POLL_INTERVAL

logger = logging.getLogger("divineruin.async_worker_claim")

# 3x POLL_INTERVAL — gives a 2-tick buffer for slow LLM+TTS rounds before a
# crashed-worker row is presumed dead and reset. Derived (not a literal) so
# tuning POLL_INTERVAL automatically updates the threshold.
STALE_RESOLVING_THRESHOLD_SECONDS = 3 * POLL_INTERVAL

# After this many revert_claim cycles on one activity, log a warning. revert_claim
# preserves the cached outcome/segments, so a persistently failing TTS (e.g.
# poisoned cached segments) would otherwise loop silently forever — each tick
# reclaims, reuses cache, fails, reverts. The counter surfaces the stuck loop for
# ops (a terminal 'failed' circuit-breaker is deferred; see debt).
RESOLVE_ATTEMPT_WARN_THRESHOLD = 5


async def claim_resolving(activity_id: str, conn: asyncpg.Connection) -> bool:
    """Atomically transition status in_progress -> resolving, stamping NOW().

    CAS semantics: the WHERE clause guards `status='in_progress'`, so concurrent
    claimants will see rowcount 0. Caller MUST hold the row via a FOR UPDATE
    lock acquired in the same transaction (the passed `conn`).

    Both `status` and `resolving_at` are set in one UPDATE so the stale-recovery
    sweep (`reset_stale_resolving`) can find crashed-worker rows by age.

    Returns True on successful claim, False if another path got there first.
    """
    # RETURNING + fetchval avoids parsing asyncpg's command-tag string ("UPDATE 1").
    # None means the WHERE clause didn't match (another claimant won).
    returned = await conn.fetchval(
        """
        UPDATE async_activities
        SET data = jsonb_set(
            jsonb_set(data, '{status}', '"resolving"'::jsonb),
            '{resolving_at}',
            to_jsonb(NOW())
        )
        WHERE id = $1 AND data->>'status' = 'in_progress'
        RETURNING id
        """,
        activity_id,
    )
    return returned is not None


async def mark_resolved(activity_id: str, updates: dict, conn: asyncpg.Connection) -> bool:
    """Terminal transition resolving -> resolved. Returns True if it applied.

    Merges `updates` (e.g. status='resolved' + narration_audio_url) AND strips
    the transient `resolving_at` + `resolve_attempts` fields in one statement, so
    resolved rows don't carry orphaned internal bookkeeping forever (it would
    otherwise leak verbatim through the raw `...data` egress in GET /activities).

    CAS-guarded on `status='resolving'`: Step D in async_worker re-opens a fresh
    txn (Step A's FOR UPDATE lock is gone), so between claim and terminal write the
    stale-recovery sweep could have reverted the row to in_progress. The guard
    makes this write a no-op (returns False) in that case rather than clobbering a
    row another tick now owns. Mirrors claim_resolving's RETURNING-id CAS shape.
    """
    returned = await conn.fetchval(
        """
        UPDATE async_activities
        SET data = (data - 'resolving_at' - 'resolve_attempts') || $2::jsonb
        WHERE id = $1 AND data->>'status' = 'resolving'
        RETURNING id
        """,
        activity_id,
        json.dumps(updates),
    )
    return returned is not None


async def revert_claim(activity_id: str, conn: asyncpg.Connection) -> None:
    """Undo a 'resolving' claim back to 'in_progress' so the next tick retries.

    Caller MUST hold the row via a FOR UPDATE lock on the passed `conn`. No-op
    if the row is no longer in the resolving state (e.g. already advanced to
    'resolved' by another path).

    Intentionally preserves any cached `outcome` / `narration_segments` /
    `narration_text` so the retry tick short-circuits the LLM call (TTS-retry
    fast path). Operator-driven resets that need a clean retry (e.g. recovering
    from a poisoned outcome) must clear those fields separately.

    Increments a `resolve_attempts` counter in the same write and warns once it
    crosses RESOLVE_ATTEMPT_WARN_THRESHOLD — a stuck retry loop (cache preserved,
    TTS failing every tick) is otherwise silent. fetchval RETURNs the new count;
    None means the row wasn't 'resolving' (no-op, already advanced).
    """
    attempts = await conn.fetchval(
        """
        UPDATE async_activities
        SET data = jsonb_set(
            (data - 'resolving_at') || '{"status": "in_progress"}'::jsonb,
            '{resolve_attempts}',
            to_jsonb(COALESCE((data->>'resolve_attempts')::int, 0) + 1)
        )
        WHERE id = $1 AND data->>'status' = 'resolving'
        RETURNING (data->>'resolve_attempts')::int
        """,
        activity_id,
    )
    if attempts is not None and attempts >= RESOLVE_ATTEMPT_WARN_THRESHOLD:
        logger.warning(
            "Activity %s reverted %d times (>= %d) — resolution may be persistently "
            "failing; a manual reset clearing cached outcome/segments may be needed",
            activity_id,
            attempts,
            RESOLVE_ATTEMPT_WARN_THRESHOLD,
        )


async def revert_claim_safe(activity_id: str) -> None:
    """Open a fresh txn and revert; swallow secondary errors so the original
    exception (if any) keeps propagating from the caller's `raise`."""
    try:
        async with db.transaction() as conn:
            await revert_claim(activity_id, conn)
    except Exception:
        logger.exception("Failed to revert resolving claim for %s", activity_id)


async def reset_stale_resolving(threshold_seconds: int = STALE_RESOLVING_THRESHOLD_SECONDS) -> int:
    """Recover crashed-worker rows: status=resolving AND resolving_at older
    than `threshold_seconds` get reset to in_progress for next-tick retry.

    Runs at the top of each tick (not inside any caller transaction), so it
    uses the pool directly. Returns the number of rows reset.
    """
    pool = await db.get_pool()
    rows = await pool.fetch(
        """
        UPDATE async_activities
        SET data = (data - 'resolving_at') || '{"status": "in_progress"}'::jsonb
        WHERE data->>'status' = 'resolving'
          AND (data->>'resolving_at')::timestamptz < NOW() - make_interval(secs => $1)
        RETURNING id
        """,
        threshold_seconds,
    )
    count = len(rows)
    if count > 0:
        logger.info("Reset %d stale 'resolving' activities back to 'in_progress'", count)
    return count
