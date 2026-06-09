"""Standalone background worker for resolving async activities.

Runs as a persistent process, polling every 5 minutes for due activities.
Resolves outcomes, generates narration, pre-renders audio.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import asdict

import db
import db_activity_queries
import db_mutations
import db_mutations_divine
import db_queries
from async_worker_claim import claim_resolving, mark_resolved, reset_stale_resolving, revert_claim_safe
from async_worker_config import POLL_INTERVAL
from async_worker_training import advance_training_cycles
from crafting_resolution import resolve_crafting_outcome
from dialogue_parser import Segment
from errand_resolution import resolve_errand_outcome
from llm_config import AUDIO_DIR, audio_url_for
from narration import generate_activity_narration, generate_notification_hook, generate_progress_snippets
from push import send_push_notification
from tts_prerender import synthesize_segments
from world_news import generate_world_news

logger = logging.getLogger("divineruin.async_worker")


async def resolve_due_activities() -> int:
    """Find and resolve all due activities. Returns count resolved."""
    # Recover presumed-dead 'resolving' claims before fetching the due list.
    try:
        await reset_stale_resolving()
    except Exception:
        logger.warning("Stale-resolving reset failed; continuing tick", exc_info=True)
    due = await db_activity_queries.get_due_activities()
    if not due:
        # Backfill progress snippets for in-progress activities even when none are due
        await _backfill_progress_snippets()
        return 0

    due_ids = {a["id"] for a in due}

    resolved_count = 0
    for activity in due:
        try:
            await _resolve_single_activity(activity)
            resolved_count += 1
        except Exception:
            logger.exception("Failed to resolve activity %s, will retry next cycle", activity["id"])

    logger.info("Resolved %d/%d due activities", resolved_count, len(due))

    # Generate world news for affected players
    if resolved_count > 0:
        affected_players = {a["player_id"] for a in due}
        for pid in affected_players:
            try:
                await generate_world_news(pid)
            except Exception:
                logger.warning("Failed to generate world news for %s", pid, exc_info=True)

    # Backfill progress snippets for remaining in-progress activities (skip just-resolved ones)
    await _backfill_progress_snippets(exclude_ids=due_ids)

    return resolved_count


async def _resolve_one_outcome(activity: dict, player_data: dict) -> dict | None:
    """Compute the rules-engine outcome for an activity. Returns None for
    unknown types (caller reverts the claim and skips)."""
    activity_type = activity.get("activity_type", "crafting")
    parameters = activity.get("parameters", {})
    if activity_type == "crafting":
        # crafting_resolution fetches the recipe category + quality tables and threads
        # them into the pure resolver (which still re-runs the workspace/tainted gates and
        # fails loud on absent gate inputs). Extracted from this over-cap module (story-003);
        # the full async_worker SRP split (debt f3194b59b4ab) stays deferred by decision.
        return await resolve_crafting_outcome(activity, player_data)
    if activity_type == "companion_errand":
        # ADR 0006: errand_resolution is the sole risk roll site.
        return await resolve_errand_outcome(player_data.get("companion", {}), parameters)
    logger.error("Unknown activity type: %s", activity_type)
    return None


async def _resolve_single_activity(activity: dict) -> None:
    """Resolve one activity: CAS-claim, do LLM+TTS outside the lock, finalize.

    On exception in the work phase, revert the claim so the next tick retries
    (cached narration short-circuits the LLM if we got past it).
    """
    activity_id = activity["id"]
    player_id = activity["player_id"]
    activity_type = activity.get("activity_type", "crafting")
    logger.info("Resolving activity %s (type=%s, player=%s)", activity_id, activity_type, player_id)

    # Step A: atomic CAS claim inside FOR-UPDATE.
    async with db.transaction() as conn:
        fresh = await db_activity_queries.get_activity(activity_id, conn=conn, for_update=True)
        if fresh is None:
            logger.warning("Activity %s vanished before claim; skipping", activity_id)
            return
        if not await claim_resolving(activity_id, conn):
            logger.info("Activity %s skipping; another path already claimed it", activity_id)
            return
        # Use the freshly-fetched row — it has the latest cached narration if a
        # prior tick got partway before TTS failed.
        activity = {**activity, **fresh}

    try:
        # Step B: outcome + narration + cache (no lock held — can be slow).
        cached_outcome = activity.get("outcome")
        cached_segments = activity.get("narration_segments")
        if cached_outcome and cached_segments:
            logger.info("Using cached narration for %s (TTS retry)", activity_id)
            outcome_dict = cached_outcome
            narration_text = activity.get("narration_text", "")
            segments = [Segment(**s) for s in cached_segments]
        else:
            player_data = await db_queries.get_player(player_id) or {}
            outcome_dict = await _resolve_one_outcome(activity, player_data)
            if outcome_dict is None:
                await revert_claim_safe(activity_id)
                return
            segments, narration_text, narration_summary = await generate_activity_narration(
                outcome_dict, player_data, activity
            )
            await db_mutations.update_activity(
                activity_id,
                {
                    "outcome": outcome_dict,
                    "narration_text": narration_text,
                    "narration_summary": narration_summary,
                    "narration_segments": [asdict(s) for s in segments],
                    "decision_options": outcome_dict.get("decision_options", []),
                },
            )
            # story-006: a crafting Failure grants +1 toward the hidden Crafting skill
            # counter (spec consolation reward, game_mechanics_crafting.md:106). Lives in
            # the non-cached branch and after the outcome is cached, so a cached-narration
            # TTS retry re-enters above and never double-increments.
            if activity_type == "crafting" and outcome_dict.get("tier") == "failure":
                await db_mutations.increment_crafting_skill_counter(player_id)

        # Step C: pre-render audio.
        audio_filename = f"{activity_id}.mp3"
        await synthesize_segments(segments, os.path.join(AUDIO_DIR, audio_filename))
        audio_url = audio_url_for(audio_filename)

        # Step D: terminal transition resolving -> resolved. Uses `mark_resolved`
        # (not `update_activity`) so the transient `resolving_at` field is stripped
        # in the same write — resolved rows don't carry an orphaned timestamp.
        async with db.transaction() as conn:
            applied = await mark_resolved(
                activity_id,
                {"status": "resolved", "narration_audio_url": audio_url},
                conn,
            )
        if not applied:
            # The stale-recovery sweep reverted this row to in_progress while we
            # rendered (work outran STALE_RESOLVING_THRESHOLD). The CAS guard kept
            # us from clobbering it; the next tick re-resolves from cached narration.
            # This is the designed self-healing path — INFO (matches
            # reset_stale_resolving), not WARNING, so a slow-TTS provider doesn't
            # emit alert-grade noise for activities that resolve fine next tick.
            logger.info(
                "Activity %s no longer 'resolving' at terminal write; skipping mark (will retry)",
                activity_id,
            )
    except asyncio.CancelledError:
        # Shutdown signal — don't open a new txn to revert (could hang). The
        # next worker boot's `reset_stale_resolving` sweep will recover the row.
        raise
    except Exception:
        await revert_claim_safe(activity_id)
        raise

    logger.info("Activity %s resolved: tier=%s", activity_id, outcome_dict.get("tier"))

    # Push notification (failure non-fatal, no revert).
    try:
        narration_hook = await generate_notification_hook(narration_text, activity_type)
        await send_push_notification(player_id, activity_title(activity_type, activity), narration_hook)
    except Exception:
        logger.warning("Failed to send push notification for %s", activity_id)


def activity_title(activity_type: str, activity: dict) -> str:
    """Build a human-readable title from activity type and parameters."""
    params = activity.get("parameters", {})
    if activity_type == "crafting":
        return params.get("result_item_name", "Crafting")
    if activity_type == "training":
        stat = params.get("stat", "")
        return f"{stat.capitalize()} Training" if stat else "Training"
    if activity_type == "companion_errand":
        errand = params.get("errand_type", "")
        return f"{errand.capitalize()} Errand" if errand else "Companion Errand"
    return "Activity"


async def _backfill_progress_snippets(exclude_ids: set[str] | None = None) -> None:
    """Generate progress snippets for in-progress activities that don't have them."""
    pool = await db.get_pool()
    rows = await pool.fetch(
        """
        SELECT id, player_id, data FROM async_activities
        WHERE data->>'status' = 'in_progress'
          AND NOT (data ? 'progress_stages')
        LIMIT 10
        """
    )

    for row in rows:
        if exclude_ids and row["id"] in exclude_ids:
            continue
        try:
            activity_data = json.loads(row["data"])
            player_data = await db_queries.get_player(row["player_id"]) or {}
            snippets = await generate_progress_snippets(activity_data, player_data)
            await db_mutations.update_activity(row["id"], {"progress_stages": snippets})
            logger.info("Generated progress snippets for %s", row["id"])
        except Exception:
            logger.warning("Failed to generate progress snippets for %s", row["id"])


async def check_god_whisper_triggers() -> int:
    """Check for players who should receive async god whispers.

    Criteria: patron != "none", favor >= threshold, no pending whisper,
    and level - last_whisper_level >= cooldown.

    Returns the number of whispers generated.
    """
    from god_whisper_data import FAVOR_WHISPER_THRESHOLD, should_trigger_whisper
    from god_whisper_generator import generate_god_whisper

    pool = await db.get_pool()
    rows = await pool.fetch(
        """
        SELECT player_id, data->'divine_favor' AS favor FROM players
        WHERE data->'divine_favor'->>'patron' IS NOT NULL
          AND data->'divine_favor'->>'patron' != 'none'
          AND (data->'divine_favor'->>'level')::int >= $1
        """,
        FAVOR_WHISPER_THRESHOLD,
    )

    count = 0
    for row in rows:
        player_id = row["player_id"]
        favor = json.loads(row["favor"])
        level = favor.get("level", 0)
        last_whisper = favor.get("last_whisper_level", 0)

        if not should_trigger_whisper(level, last_whisper):
            continue

        # Check no pending whisper already exists
        pending = await db_activity_queries.get_pending_god_whispers(player_id)
        if pending:
            continue

        patron_id = favor.get("patron", "none")
        try:
            await generate_god_whisper(player_id, patron_id)
            await db_mutations_divine.mark_favor_whisper_level(player_id, level)
            count += 1
        except Exception:
            logger.exception("Failed to generate god whisper for %s", player_id)

    if count > 0:
        logger.info("Generated %d god whispers", count)
    return count


async def main() -> None:
    """Main entry point for the async worker."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logger.info("Async worker starting, poll interval: %ds", POLL_INTERVAL)

    await db.get_pool()
    logger.info("Database connection established")

    # Load content-backed config. Fail loud if the query fails — the rules
    # engine depends on these maps being populated before the polling loop starts.
    from abilities import load_abilities
    from archetypes import load_archetypes
    from mentor_variants import load_mentor_variants
    from milestones import load_milestones
    from npcs import load_npcs
    from role_archetypes import load_role_archetypes
    from spells import load_spells
    from training_rules import load_training_activity_types

    await load_training_activity_types()
    await load_archetypes()
    await load_abilities()
    await load_milestones()
    await load_spells()
    await load_mentor_variants()
    await load_role_archetypes()
    await load_npcs()

    try:
        while True:
            try:
                count = await resolve_due_activities()
                if count > 0:
                    logger.info("Cycle complete: %d activities resolved", count)
            except Exception:
                logger.exception("Error in resolve cycle")

            try:
                await advance_training_cycles()
            except Exception:
                logger.exception("Error in training cycle advancement")

            try:
                await check_god_whisper_triggers()
            except Exception:
                logger.exception("Error in god whisper check")

            await asyncio.sleep(POLL_INTERVAL)
    finally:
        await db.close_all()


if __name__ == "__main__":
    asyncio.run(main())
