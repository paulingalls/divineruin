"""Standalone background worker for resolving async activities.

Runs as a persistent process, polling every 5 minutes for due activities.
Resolves outcomes, generates narration, pre-renders audio.
"""

import asyncio
import logging
import os
from dataclasses import asdict

import db
from activity_templates import get_companion_context, get_crafting_npc, get_training_mentor
from async_rules import resolve_companion_errand, resolve_crafting, resolve_training
from narration import generate_activity_narration
from tts_prerender import synthesize_to_file

logger = logging.getLogger("divineruin.async_worker")

POLL_INTERVAL = 300  # 5 minutes
AUDIO_DIR = os.environ.get("ASYNC_AUDIO_DIR", os.path.join(os.path.dirname(__file__), "..", "server", "audio"))


async def resolve_due_activities() -> int:
    """Find and resolve all due activities. Returns count resolved."""
    due = await db.get_due_activities()
    if not due:
        return 0

    resolved_count = 0
    for activity in due:
        try:
            await _resolve_single_activity(activity)
            resolved_count += 1
        except Exception:
            logger.exception("Failed to resolve activity %s, will retry next cycle", activity["id"])

    logger.info("Resolved %d/%d due activities", resolved_count, len(due))
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
    audio_url = f"/api/audio/{audio_filename}"

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
