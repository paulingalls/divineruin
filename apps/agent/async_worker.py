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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from training_rules import CompletionResult

import db
import db_activity_queries
import db_content_queries
import db_mutations
import db_queries
import db_training
import skill_persistence
from async_rules import resolve_companion_errand, resolve_crafting
from dialogue_parser import Segment
from errand_risk import numeric_to_danger, roll_errand_risk
from llm_config import AUDIO_DIR, audio_url_for
from narration import generate_activity_narration, generate_notification_hook, generate_progress_snippets
from push import send_push_notification
from tts_prerender import synthesize_segments
from world_news import generate_world_news

logger = logging.getLogger("divineruin.async_worker")

POLL_INTERVAL = 300  # 5 minutes


async def apply_skill_practice_advancement(
    player_id: str,
    training_skill: str,
    counter_increment: int,
    *,
    queries=db_queries,
    mutations=db_mutations,
) -> dict | None:
    """Increment the skill_advancement counter from a skill_practice training completion.

    Delegates to `skill_persistence.apply_skill_use_with_persistence` —
    the single function both this path and the session-use path
    (`check_tools._request_skill_check_impl`) call, enforcing the M1.2
    hybrid-counter contract by construction.

    Returns advancement info dict (advanced, new_tier) or None when no advancement.
    """
    adv = await skill_persistence.apply_skill_use_with_persistence(
        player_id,
        training_skill,
        counter_increment,
        queries=queries,
        mutations=mutations,
    )
    if adv is None:
        return None
    return {"advanced": adv.advanced, "new_tier": adv.new_tier}


async def resolve_due_activities() -> int:
    """Find and resolve all due activities. Returns count resolved."""
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


async def _resolve_single_activity(activity: dict) -> None:
    """Resolve a single activity: compute outcome, generate narration, render audio."""
    activity_id = activity["id"]
    player_id = activity["player_id"]
    activity_type = activity.get("activity_type", "crafting")
    parameters = activity.get("parameters", {})

    logger.info("Resolving activity %s (type=%s, player=%s)", activity_id, activity_type, player_id)

    # Check for cached narration from a previous partial resolve (e.g. TTS failed)
    cached_outcome = activity.get("outcome")
    cached_segments = activity.get("narration_segments")

    if cached_outcome and cached_segments:
        logger.info("Using cached narration for %s (TTS retry)", activity_id)
        outcome_dict = cached_outcome
        narration_text = activity.get("narration_text", "")
        segments = [Segment(**s) for s in cached_segments]
    else:
        # Load player data
        player_data = await db_queries.get_player(player_id) or {}

        # Compute outcome using rules engine
        if activity_type == "crafting":
            outcome = resolve_crafting(player_data, parameters)
        elif activity_type == "companion_errand":
            companion_data = player_data.get("companion", {})
            outcome = resolve_companion_errand(companion_data, parameters)
        else:
            logger.error("Unknown activity type: %s", activity_type)
            return

        outcome_dict = asdict(outcome)

        if activity_type == "companion_errand":
            # Risk is rolled here (sole authority), not at dispatch — nothing reads
            # it before resolution, so the timing is behaviorally identical (ADR 0006).
            location = await db_content_queries.get_location(parameters.get("destination", ""))
            danger = numeric_to_danger(location.get("danger_level") if location else None)
            risk = roll_errand_risk(
                parameters.get("errand_type", "scout"),
                danger,
                companion_data.get("id", ""),
            )
            outcome_dict.setdefault("narrative_context", {})["risk_outcome"] = risk

        # Generate structured narration via LLM tool_use
        segments, narration_text, narration_summary = await generate_activity_narration(
            outcome_dict, player_data, activity
        )

        # Cache everything so retries skip the LLM call
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

    # Pre-render audio from structured segments
    audio_filename = f"{activity_id}.mp3"
    audio_path = os.path.join(AUDIO_DIR, audio_filename)
    await synthesize_segments(segments, audio_path)
    audio_url = audio_url_for(audio_filename)

    # Mark fully resolved
    await db_mutations.update_activity(
        activity_id,
        {
            "status": "resolved",
            "narration_audio_url": audio_url,
        },
    )

    logger.info("Activity %s resolved: tier=%s", activity_id, outcome_dict.get("tier"))

    # Send push notification
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


def build_training_completion_outcome(
    completion: CompletionResult,
    data: dict,
    adv_info: dict | None,
) -> dict:
    """Build an outcome dict for training completion narration.

    Maps CompletionResult + activity data into the format expected by
    build_narration_prompt("training_completion", outcome).
    """
    skill_advanced = adv_info["advanced"] if adv_info else False
    tier = "breakthrough" if skill_advanced else "plateau"

    return {
        "narrative_context": {
            "mentor_id": data.get("mentor_id", "guildmaster_torin"),
            "training_stat": data.get("stat", "unknown"),
            "training_skill": data.get("skill"),
            "tier": tier,
            "dc": data.get("dc", "?"),
        },
        "stat_gains": {
            "counter_increment": completion.counter_increment,
            "micro_bonus": completion.micro_bonus,
            "skill_advanced": skill_advanced,
            "new_tier": adv_info["new_tier"] if adv_info else None,
        },
        "decision_options": [],
    }


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


async def advance_training_cycles() -> int:
    """Poll for training activities whose transition_at has passed and advance state.

    running_first_half → awaiting_decision (sends notification)
    running_second_half → complete (applies outcome, increments skill counter)

    Returns count of transitions applied.
    """
    from training_rules import complete_training_cycle, get_midpoint_decision

    due = await db_training.get_due_training_transitions()
    if not due:
        return 0

    count = 0
    for activity in due:
        activity_id = activity["id"]
        player_id = activity["player_id"]
        activity_type = activity["activity_type"]
        state = activity["state"]
        data = activity.get("data", {})

        try:
            if state == "running_first_half":
                decision = get_midpoint_decision(activity_type)
                await db_training.update_training_activity(
                    activity_id,
                    "awaiting_decision",
                    {
                        "decision_presented": True,
                        "decision_prompt": decision.prompt,
                        "decision_options": [{"id": o.id, "label": o.label} for o in decision.options],
                    },
                )
                logger.info("Training %s → awaiting_decision (player=%s)", activity_id, player_id)

                # Send push notification for midpoint decision
                try:
                    program_name = data.get("program_name", "Training")
                    await send_push_notification(
                        player_id,
                        f"{program_name} — Decision Needed",
                        decision.prompt[:100],
                    )
                except Exception:
                    logger.warning("Failed to send midpoint notification for %s", activity_id)

                count += 1

            elif state == "running_second_half":
                decision_id = data.get("decision_id", "")
                completion = complete_training_cycle(activity_type, decision_id)

                # Check for cached narration (TTS retry — skill advancement already applied)
                cached_segments = data.get("narration_segments")
                cached_text = data.get("narration_text")

                if cached_segments and cached_text:
                    logger.info("Using cached narration for %s (TTS retry)", activity_id)
                    segments = [Segment(**s) for s in cached_segments]
                    narration_text = cached_text
                    adv_info = None
                    if data.get("skill_advanced") is not None:
                        adv_info = {"advanced": data["skill_advanced"], "new_tier": data.get("new_tier")}
                else:
                    adv_info: dict | None = None

                    # Skill practice: increment the skill use counter (hybrid advancement —
                    # shares the skill_advancement row with the session-use path in check_tools).
                    if activity_type == "skill_practice" and completion.counter_increment > 0:
                        training_skill = data.get("skill")
                        if training_skill:
                            adv_info = await apply_skill_practice_advancement(
                                player_id, training_skill, completion.counter_increment
                            )
                        else:
                            logger.warning("Training %s is skill_practice but missing 'skill' in data", activity_id)

                    # Generate narration via LLM
                    player_data = await db_queries.get_player(player_id) or {}
                    outcome = build_training_completion_outcome(completion, data, adv_info)
                    segments, narration_text, narration_summary = await generate_activity_narration(
                        outcome, player_data, {"activity_type": "training_completion"}
                    )

                    # Cache narration + advancement so retries skip LLM and skill writes
                    cache_data: dict = {
                        "narration_text": narration_text,
                        "narration_summary": narration_summary,
                        "narration_segments": [asdict(s) for s in segments],
                    }
                    if adv_info:
                        cache_data["skill_advanced"] = adv_info["advanced"]
                        cache_data["new_tier"] = adv_info["new_tier"]
                    await db_training.update_training_activity(
                        activity_id,
                        "running_second_half",
                        cache_data,
                    )

                # Pre-render TTS audio
                audio_filename = f"{activity_id}.mp3"
                audio_path = os.path.join(AUDIO_DIR, audio_filename)
                await synthesize_segments(segments, audio_path)
                audio_url = audio_url_for(audio_filename)

                # Mark complete with outcome data
                update_data: dict = {
                    "counter_increment": completion.counter_increment,
                    "micro_bonus": completion.micro_bonus,
                    "narration_audio_url": audio_url,
                }
                if adv_info:
                    update_data["skill_advanced"] = adv_info["advanced"]
                    update_data["new_tier"] = adv_info["new_tier"]

                await db_training.update_training_activity(activity_id, "complete", update_data)
                logger.info("Training %s → complete (player=%s, type=%s)", activity_id, player_id, activity_type)

                # Send completion notification
                try:
                    narration_hook = await generate_notification_hook(narration_text, "training")
                    await send_push_notification(player_id, "Training Complete", narration_hook)
                except Exception:
                    logger.warning("Failed to send completion notification for %s", activity_id)

                count += 1

        except Exception:
            logger.exception("Failed to advance training %s, will retry next cycle", activity_id)

    if count > 0:
        logger.info("Advanced %d/%d training cycles", count, len(due))
    return count


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
            await db_mutations.mark_favor_whisper_level(player_id, level)
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
    # engine depends on this map being populated before the polling loop starts.
    from training_rules import load_training_activity_types

    await load_training_activity_types()

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
