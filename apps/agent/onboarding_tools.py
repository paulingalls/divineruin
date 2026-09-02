"""Onboarding tools — beat advancement for the OnboardingAgent."""

import json
import logging
import time

from livekit.agents import Agent
from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import db_mutations
import db_queries
from session_data import SessionData

logger = logging.getLogger("divineruin.onboarding_tools")

ONBOARDING_COMPLETE = "complete"

BEAT_NAMES = {
    1: "arrival",
    2: "market",
    3: "companion_meeting",
    4: "kael_suggestion",
    5: "first_destination",
}


@function_tool
async def advance_onboarding_beat(context: RunContext) -> str | tuple[Agent, str]:
    """Advance to the next onboarding beat.

    Call when the current beat's completion conditions are met.
    Beat 1 (Arrival): After initial narration delivered.
    Beat 2 (Market): After 2-3 player exchanges or player attempts to leave.
    Beat 3 (Companion Meeting): After Kael has introduced himself and companion state initialized.
    Beat 4 (Kael's Suggestion): After player indicates a direction or asks Kael to lead.
    Beat 5 (First Destination): After Greyvale quest hook delivered.
    """
    sd: SessionData = context.userdata

    if sd.onboarding_beat is None:
        raise ToolError("Not in onboarding mode.")

    current = sd.onboarding_beat

    if current >= 5:
        companion = sd.companion
        if companion is None:
            raise RuntimeError(f"Player {sd.player_id!r} completed onboarding without a companion")

        # Beat 5 complete — hand off to open-world exploration (city region).
        sd.onboarding_beat = None
        await db_mutations.set_player_flag(sd.player_id, "onboarding_beat", ONBOARDING_COMPLETE)

        from livekit.agents.llm import ChatContext

        from gameplay_agent import create_gameplay_agent
        from region_types import REGION_CITY

        summary_ctx = ChatContext()
        summary_ctx.add_message(
            role="system",
            content=(
                f"Player completed onboarding. They met companion {companion.name}, "
                "explored the Accord of Tides market, and received the "
                "Greyvale quest hook. Begin open-world gameplay."
            ),
        )
        result = json.dumps({"onboarding_complete": True, "location": sd.location_id})
        return (
            create_gameplay_agent(
                REGION_CITY,
                sd.location_id,
                companion=companion,
                chat_ctx=summary_ctx,
            ),
            result,
        )

    archetype_id = None
    if current == 3:
        player = await db_queries.get_player(sd.player_id)
        if player is None:
            raise RuntimeError(f"Player {sd.player_id!r} missing during companion assignment")
        archetype_id = player["class"]

    next_beat = current + 1
    sd.onboarding_beat = next_beat
    await db_mutations.set_player_flag(sd.player_id, "onboarding_beat", next_beat)

    if current == 3:
        from companion_relationship_queries import hydrate_assigned_companion_state

        assert archetype_id is not None
        companion = await hydrate_assigned_companion_state(sd.player_id, archetype_id)
        companion.last_speech_time = time.time()
        sd.companion = companion
        await db_mutations.set_player_flag(sd.player_id, "companion_met", True)
        logger.info("Companion %s initialized for player %s after beat 3", companion.name, sd.player_id)

    beat_name = BEAT_NAMES.get(next_beat, "unknown")
    logger.info("Player %s advanced to onboarding beat %d (%s)", sd.player_id, next_beat, beat_name)

    return json.dumps({"beat": next_beat, "beat_name": beat_name})
