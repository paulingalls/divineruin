"""Onboarding tools — beat advancement for the OnboardingAgent."""

import json
import logging
import time

from livekit.agents import Agent
from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import db_mutations
import db_queries
from action_sound_content import ACTION_SOUND_EXPORTS, publish_action_sound
from session_data import SessionData

logger = logging.getLogger("divineruin.onboarding_tools")

ONBOARDING_COMPLETE = "complete"

BEAT_NAMES = {
    1: "arrival",
    2: "market",
    3: "companion_meeting",
}
FINAL_BEAT = max(BEAT_NAMES)


@function_tool
async def advance_onboarding_beat(context: RunContext) -> str | tuple[Agent, str]:
    """Advance to the next onboarding beat.

    Call when the current beat's completion conditions are met.
    Beat 1 (Arrival): After initial narration delivered.
    Beat 2 (Market): After 2-3 player exchanges.
    Beat 3 (Companion Meeting): After introduction, initialize the companion and hand off to exploration.
    """
    sd: SessionData = context.userdata

    if sd.onboarding_beat is None:
        raise ToolError("Not in onboarding mode.")

    current = sd.onboarding_beat

    if current == FINAL_BEAT:
        from companion_relationship_queries import hydrate_assigned_companion_state

        # Assignment must succeed before completion so a failed selection is replayable.
        player = await db_queries.get_player(sd.player_id)
        if player is None:
            raise ToolError(f"Player {sd.player_id!r} missing during companion assignment")
        companion = await hydrate_assigned_companion_state(sd.player_id, player["class"], player["level"])
        companion.last_speech_time = time.time()
        sd.companion = companion
        await db_mutations.set_player_flag(sd.player_id, "companion_met", True)
        await db_mutations.set_player_flag(sd.player_id, "onboarding_beat", ONBOARDING_COMPLETE)
        sd.onboarding_beat = None

        from livekit.agents.llm import ChatContext

        from gameplay_agent import create_gameplay_agent
        from region_types import REGION_CITY

        summary_ctx = ChatContext()
        summary_ctx.add_message(
            role="system",
            content=(
                f"Player completed onboarding. They met companion {companion.name}, "
                f"and remain at {sd.location_id}. Begin open-world gameplay."
            ),
        )
        result = json.dumps({"onboarding_complete": True, "location": sd.location_id})
        agent = create_gameplay_agent(
            REGION_CITY,
            sd.location_id,
            companion=companion,
            chat_ctx=summary_ctx,
        )
        sound_id = ACTION_SOUND_EXPORTS["ACTION_ADVANCE_ONBOARDING_BEAT"]
        await publish_action_sound(sd, sound_id)
        return agent, result

    next_beat = current + 1
    sd.onboarding_beat = next_beat
    await db_mutations.set_player_flag(sd.player_id, "onboarding_beat", next_beat)
    sound_id = ACTION_SOUND_EXPORTS["ACTION_ADVANCE_ONBOARDING_BEAT"]
    await publish_action_sound(sd, sound_id)

    beat_name = BEAT_NAMES.get(next_beat, "unknown")
    logger.info("Player %s advanced to onboarding beat %d (%s)", sd.player_id, next_beat, beat_name)

    return json.dumps({"beat": next_beat, "beat_name": beat_name})
