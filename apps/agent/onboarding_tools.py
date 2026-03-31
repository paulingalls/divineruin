"""Onboarding tools — beat advancement for the OnboardingAgent."""

import json
import logging
import time

from livekit.agents import Agent
from livekit.agents.llm import function_tool
from livekit.agents.voice import RunContext

import db
from session_data import CompanionState, SessionData

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
        return json.dumps({"error": "Not in onboarding mode."})

    current = sd.onboarding_beat

    if current >= 5:
        # Beat 5 complete — handoff to CityAgent
        sd.onboarding_beat = None
        await db.set_player_flag(sd.player_id, "onboarding_beat", ONBOARDING_COMPLETE)

        from livekit.agents.llm import ChatContext

        from city_agent import CityAgent

        summary_ctx = ChatContext()
        summary_ctx.add_message(
            role="system",
            content=(
                "Player completed onboarding. They met companion Kael, "
                "explored the Accord of Tides market, and received the "
                "Greyvale quest hook. Begin open-world gameplay."
            ),
        )
        result = json.dumps({"onboarding_complete": True, "location": sd.location_id})
        companion = sd.companion
        return (
            CityAgent(
                initial_location=sd.location_id,
                companion=companion,
                chat_ctx=summary_ctx,
            ),
            result,
        )

    # Advance to next beat
    next_beat = current + 1
    sd.onboarding_beat = next_beat
    await db.set_player_flag(sd.player_id, "onboarding_beat", next_beat)

    if current == 3:
        sd.companion = CompanionState(
            id="companion_kael",
            name="Kael",
            last_speech_time=time.time(),
        )
        await db.set_player_flag(sd.player_id, "companion_met", True)
        logger.info("Companion Kael initialized for player %s after beat 3", sd.player_id)

    beat_name = BEAT_NAMES.get(next_beat, "unknown")
    logger.info("Player %s advanced to onboarding beat %d (%s)", sd.player_id, next_beat, beat_name)

    return json.dumps({"beat": next_beat, "beat_name": beat_name})
