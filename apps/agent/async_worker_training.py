"""Training-cycle state machine for the async worker.

Extracted from async_worker.py (file-size touch-split, debt f3194b59b4ab):
the training two-phase progression (running_first_half -> awaiting_decision ->
running_second_half -> complete) plus its skill-advancement and completion-outcome
helpers. async_worker.main() drives this via advance_training_cycles(); the
crafting/errand activity-resolution path and the worker loop stay in async_worker.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from training_rules import CompletionResult

import db_mutations
import db_queries
import db_training
import skill_persistence
from dialogue_parser import Segment
from llm_config import AUDIO_DIR, audio_url_for
from narration import generate_activity_narration, generate_notification_hook
from push import send_push_notification
from tts_prerender import synthesize_segments

logger = logging.getLogger("divineruin.async_worker_training")


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
    (`check_tools._check_skill_impl`) call, enforcing the M1.2
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
