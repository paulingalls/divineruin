"""Standalone background worker for resolving async activities.

Runs as a persistent process, polling every 5 minutes for due activities.
Resolves outcomes, generates narration, pre-renders audio.
"""

import asyncio
import json
import logging
import os
from dataclasses import asdict

import db
from activity_templates import get_companion_context, get_crafting_npc, get_training_mentor
from async_rules import resolve_companion_errand, resolve_crafting, resolve_training
from llm_config import AUDIO_DIR, audio_url_for
from narration import generate_activity_narration, generate_notification_hook, generate_progress_snippets
from tts_prerender import synthesize_to_file
from world_news import generate_world_news

logger = logging.getLogger("divineruin.async_worker")

POLL_INTERVAL = 300  # 5 minutes


async def resolve_due_activities() -> int:
    """Find and resolve all due activities. Returns count resolved."""
    due = await db.get_due_activities()
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
                logger.warning("Failed to generate world news for %s", pid)

    # Backfill progress snippets for remaining in-progress activities (skip just-resolved ones)
    await _backfill_progress_snippets(exclude_ids=due_ids)

    return resolved_count


async def _resolve_single_activity(activity: dict) -> None:
    """Resolve a single activity: compute outcome, generate narration, render audio."""
    activity_id = activity["id"]
    player_id = activity["player_id"]
    activity_type = activity.get("activity_type", "crafting")
    parameters = activity.get("parameters", {})

    logger.info("Resolving activity %s (type=%s, player=%s)", activity_id, activity_type, player_id)

    # Load player data
    player_data = await db.get_player(player_id) or {}

    # Compute outcome using rules engine
    if activity_type == "crafting":
        outcome = resolve_crafting(player_data, parameters)
    elif activity_type == "training":
        outcome = resolve_training(player_data, parameters)
    elif activity_type == "companion_errand":
        companion_data = player_data.get("companion", {})
        outcome = resolve_companion_errand(companion_data, parameters)
    else:
        logger.error("Unknown activity type: %s", activity_type)
        return

    outcome_dict = asdict(outcome)

    # Generate narration via LLM
    narration_text = await generate_activity_narration(outcome_dict, player_data, activity)

    # Pre-render audio
    voice_id = _get_voice_id(activity_type, parameters, outcome_dict)
    audio_filename = f"{activity_id}.mp3"
    audio_path = os.path.join(AUDIO_DIR, audio_filename)
    await synthesize_to_file(narration_text, voice_id, audio_path)
    audio_url = audio_url_for(audio_filename)

    # Update activity in DB with all results
    await db.update_activity(
        activity_id,
        {
            "status": "resolved",
            "outcome": outcome_dict,
            "narration_text": narration_text,
            "narration_audio_url": audio_url,
            "decision_options": outcome_dict.get("decision_options", []),
        },
    )

    logger.info("Activity %s resolved: tier=%s", activity_id, outcome_dict.get("tier"))

    # Send push notification
    try:
        narration_hook = await generate_notification_hook(narration_text, activity_type)
        await _send_push_notification(player_id, activityTitle(activity_type, activity), narration_hook)
    except Exception:
        logger.warning("Failed to send push notification for %s", activity_id)


def activityTitle(activity_type: str, activity: dict) -> str:
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


async def _send_push_notification(player_id: str, title: str, body: str) -> None:
    """Send push notification via the server's push endpoint."""
    import aiohttp

    server_url = os.environ.get("SERVER_URL", "http://localhost:3001")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{server_url}/api/internal/push",
                json={"player_id": player_id, "title": title, "body": body},
                headers={"X-Internal-Secret": os.environ.get("INTERNAL_SECRET", "")},
            ) as resp:
                if resp.status != 200:
                    logger.warning("Push notification failed: %s", resp.status)
    except Exception:
        logger.warning("Could not reach server for push notification")


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
            player_data = await db.get_player(row["player_id"]) or {}
            snippets = await generate_progress_snippets(activity_data, player_data)
            await db.update_activity(row["id"], {"progress_stages": snippets})
            logger.info("Generated progress snippets for %s", row["id"])
        except Exception:
            logger.warning("Failed to generate progress snippets for %s", row["id"])


def _get_voice_id(activity_type: str, parameters: dict, outcome: dict) -> str:
    """Determine the voice ID for TTS based on activity type."""
    ctx = outcome.get("narrative_context", {})
    if activity_type == "crafting":
        npc = get_crafting_npc(ctx.get("npc_id", "grimjaw_blacksmith"))
        return npc["voice_id"]
    elif activity_type == "training":
        mentor = get_training_mentor(ctx.get("mentor_id", "guildmaster_torin"))
        return mentor["voice_id"]
    else:
        companion = get_companion_context(ctx.get("companion_id", "companion_kael"))
        return companion["voice_id"]


async def main() -> None:
    """Main entry point for the async worker."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logger.info("Async worker starting, poll interval: %ds", POLL_INTERVAL)

    await db.get_pool()
    logger.info("Database connection established")

    try:
        while True:
            try:
                count = await resolve_due_activities()
                if count > 0:
                    logger.info("Cycle complete: %d activities resolved", count)
            except Exception:
                logger.exception("Error in resolve cycle")
            await asyncio.sleep(POLL_INTERVAL)
    finally:
        await db.close_all()


if __name__ == "__main__":
    asyncio.run(main())
