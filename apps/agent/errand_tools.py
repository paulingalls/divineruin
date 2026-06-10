"""Companion-errand agent tools on DispatchAgent (story-009).

`dispatch_companion_errand` validates and creates an async_activities row; the
async worker resolves it later (risk rolled at resolution, ADR 0006).
`resolve_companion_errand` computes the outcome on demand via the shared
errand_resolution helper, returning the same shape the worker produces.

Errors raise LiveKit `ToolError` (ADR 0002). The `_*_impl` helpers expose
`*_mod=` / `now_fn=` / `rng=` keyword seams for TEST-ONLY injection; production
callers use the `@function_tool` wrappers. Errand durations / valid_destinations /
blocked_companions come from the shared errand_templates content (story-011).
"""

import asyncio
import json
import logging
import random
from datetime import UTC, datetime, timedelta

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import companion_relationship_queries
import db
import db_activity_queries
import db_content_queries
import db_mutations
import db_queries
import errand_risk
from errand_resolution import resolve_errand_outcome
from session_data import SessionData
from tool_support import _validate_id

logger = logging.getLogger("divineruin.tools")

# Companion-slot cap for the agent's dispatch-time pre-check. Mirrors the
# companion slot of the LOCKED 3-independent-slot model whose authoritative
# validator lives in apps/server/src/slot_validation.ts (1 companion errand at a
# time). Kept as a local constant — a single LOCKED-spec integer — rather than a
# shared source; if the slot model ever changes, update both deliberately.
_COMPANION_SLOT_CAP = 1

# Wait-with-retry for a resolve that races the background worker (story-014).
# The worker's resolve window is 10-30s; the player asks within one voice turn,
# so when the row is mid-'resolving' we poll briefly for the worker to land its
# outcome before raising. Budget is deliberately SHORT (~1.5s worst case): the
# worker writes its outcome late (after narration), so most 'resolving' hits
# still raise — only the immediate boundary race wins. A longer poll would just
# add dead air to the common (still-out) path, fighting the 1500ms latency rule.
_RESOLVE_POLL_ATTEMPTS = 2  # initial read + 1 retry
_RESOLVE_POLL_INTERVAL_SECONDS = 1.5


@function_tool()
async def dispatch_companion_errand(
    context: RunContext[SessionData],
    companion_id: str,
    errand_type: str,
    destination: str,
) -> str:
    """Send a companion on an errand. Use only after the player has audibly chosen
    a companion, an errand kind, and where to send them.

    Errand kinds: scout (investigate a place), social (gather gossip/leads),
    acquire (find a resource/item), relationship (visit an NPC). The companion
    returns later with a narrated result — call resolve_companion_errand then.

    Returns an error if the errand kind is unknown, the destination isn't valid
    for that kind, the companion can't perform it, the destination is too
    dangerous for that errand, or the companion is already on an errand.

    Args:
        companion_id: The companion to send (e.g. companion_kael).
        errand_type: scout | social | acquire | relationship.
        destination: A location id valid for this errand kind.
    """
    return await _dispatch_companion_errand_impl(context, companion_id, errand_type, destination)


async def _dispatch_companion_errand_impl(
    context: RunContext[SessionData],
    companion_id: str,
    errand_type: str,
    destination: str,
    *,
    content_mod=db_content_queries,
    activity_mod=db_activity_queries,
    mutations_mod=db_mutations,
    risk_mod=errand_risk,
    now_fn=None,
    rng: random.Random | None = None,
) -> str:
    context.disallow_interruptions()
    _validate_id(companion_id, "companion_id")
    _validate_id(errand_type, "errand_type")
    _validate_id(destination, "destination")
    session: SessionData = context.userdata
    player_id = session.player_id
    logger.info(
        "dispatch_companion_errand: player=%s companion=%s errand=%s dest=%s",
        player_id,
        companion_id,
        errand_type,
        destination,
    )

    template = await content_mod.get_errand_template(errand_type)
    if template is None:
        raise ToolError(f"Unknown errand kind: {errand_type}")
    if destination not in template["valid_destinations"]:
        raise ToolError(f"{destination} is not a valid destination for a {errand_type} errand.")
    if companion_id in template["blocked_companions"]:
        raise ToolError(f"{companion_id} cannot perform {errand_type} errands.")

    location = await content_mod.get_location(destination)
    try:
        danger = risk_mod.numeric_to_danger(location.get("danger_level") if location else None)
    except ValueError as e:
        # Malformed seed danger_level — fail clean to the LLM, not a raw ValueError.
        raise ToolError(f"{destination} has an invalid danger level; cannot dispatch there.") from e
    if risk_mod.is_blocked_combo(danger, errand_type):
        raise ToolError(f"{errand_type} errands are not available at {danger} destinations.")

    slot_counts = await activity_mod.count_active_by_slot(player_id)
    if slot_counts["companion"] >= _COMPANION_SLOT_CAP:
        raise ToolError("Your companion is already on an errand. Wait for them to return first.")

    now = (now_fn or _default_now)()
    duration_seconds = (rng or random.Random()).randint(
        template["duration_min_seconds"], template["duration_max_seconds"]
    )
    resolve_at = now + timedelta(seconds=duration_seconds)

    data = {
        "status": "in_progress",
        "activity_type": "companion_errand",
        "start_time": now.isoformat(),
        "duration_min_seconds": template["duration_min_seconds"],
        "duration_max_seconds": template["duration_max_seconds"],
        "resolve_at": resolve_at.isoformat(),
        "parameters": {"errand_type": errand_type, "destination": destination},
        "outcome": None,
        "narration_text": None,
        "narration_audio_url": None,
        "decision_options": None,
    }
    activity_id = await mutations_mod.create_async_activity(player_id, data)

    return json.dumps(
        {
            "activity_id": activity_id,
            "resolve_at_estimate": resolve_at.isoformat(),
            "errand_type": errand_type,
            "destination": destination,
        }
    )


@function_tool()
async def resolve_companion_errand(
    context: RunContext[SessionData],
    errand_id: str,
) -> str:
    """Resolve a companion's errand and report what happened. Use when the player
    asks how the errand went (after enough time has passed). Returns the outcome
    tier, narration context, and the decision options to offer the player.

    Args:
        errand_id: The activity_id returned by dispatch_companion_errand.
    """
    return await _resolve_companion_errand_impl(context, errand_id)


async def _resolve_companion_errand_impl(
    context: RunContext[SessionData],
    errand_id: str,
    *,
    db_mod=db,
    activity_mod=db_activity_queries,
    queries_mod=db_queries,
    mutations_mod=db_mutations,
    resolve_fn=resolve_errand_outcome,
    companion_rel_mod=companion_relationship_queries,
    now_fn=None,
    sleep_fn=None,
) -> str:
    context.disallow_interruptions()
    _validate_id(errand_id, "errand_id")
    session: SessionData = context.userdata
    player_id = session.player_id
    logger.info("resolve_companion_errand: player=%s errand=%s", player_id, errand_id)

    sleep = sleep_fn or asyncio.sleep

    # Wait-with-retry: a row mid-'resolving' means the worker is mid-flight, so we
    # re-read in a FRESH short transaction each attempt — releasing FOR UPDATE
    # before every sleep (never held across a sleep) — giving the worker a brief
    # window to land its outcome before we raise. Any non-'resolving' row resolves
    # authoritatively on the first attempt, exactly as a single transaction would.
    for attempt in range(_RESOLVE_POLL_ATTEMPTS):
        # Resource-row template: lock the row FOR UPDATE so the read→roll→write is
        # atomic — two concurrent resolves (or one racing the worker) can't both
        # roll before the status persists (ADR 0006: risk rolls once, at resolution).
        async with db_mod.transaction() as conn:
            activity = await activity_mod.get_activity(errand_id, conn=conn, for_update=True)
            if activity is None:
                raise ToolError(f"Unknown errand: {errand_id}")
            if activity["player_id"] != player_id:
                raise ToolError(f"Errand {errand_id} does not belong to this player.")

            # Already resolved (worker or a prior resolve), OR the worker wrote its
            # outcome mid-'resolving' (Step B, before flipping to 'resolved') —
            # return the canonical persisted outcome, never re-roll, so the DM's
            # account matches the push.
            cached = activity.get("outcome")
            if cached is not None:
                return json.dumps(cached)

            if activity.get("status") != "resolving":
                # Time gate: the companion is still out until resolve_at passes (the
                # worker uses the same resolve_at <= NOW() gate).
                now = (now_fn or _default_now)()
                resolve_at = activity.get("resolve_at")
                if resolve_at is not None and now < datetime.fromisoformat(resolve_at):
                    raise ToolError(f"The companion is still out on errand {errand_id}; ask again later.")

                # Only load the player once we're committed to resolving.
                player = await queries_mod.get_player(player_id) or {}
                companion_data = player.get("companion", {})
                companion_id = companion_data.get("id")
                if companion_id:
                    # Feed the bonus the live effective rank (session_count + affinity), not the
                    # stale players.data int (M6.4 / story-003). Same FOR UPDATE lock.
                    companion_data["relationship_tier"] = await companion_rel_mod.cached_effective_rank(
                        player_id, companion_id, conn=conn
                    )
                outcome = await resolve_fn(companion_data, activity.get("parameters", {}))
                if companion_id:
                    # Persist the HYBRID affinity nudge atomically with the resolve (same lock).
                    await companion_rel_mod.apply_errand_affinity(
                        player_id, companion_id, outcome.get("relationship_change", 0), conn=conn
                    )

                # Persist + mark resolved within the lock so the worker skips this
                # row (get_due_activities filters status='in_progress').
                await mutations_mod.update_activity(
                    errand_id,
                    {
                        "status": "resolved",
                        "outcome": outcome,
                        "decision_options": outcome.get("decision_options", []),
                    },
                    conn=conn,
                )
                return json.dumps(outcome)
            # status == 'resolving': exit the `async with` (RELEASE the lock), then
            # sleep below before re-reading — the worker holds no lock during its
            # slow narration window, so the next attempt sees the outcome it lands.
        if attempt < _RESOLVE_POLL_ATTEMPTS - 1:
            await sleep(_RESOLVE_POLL_INTERVAL_SECONDS)

    # The worker out-ran the poll window. Fail closed so the player retries rather
    # than the tool double-rolling a divergent outcome.
    raise ToolError(f"Errand {errand_id} is currently being resolved by the background worker; ask again in a moment.")


def _default_now() -> datetime:
    return datetime.now(UTC)
