"""OnboardingAgent — guided first 10-15 minutes for new players.

Haiku model, city-appropriate tools, scripted 5-beat sequence.
Lightweight BackgroundProcess for beats 4-5 (stall detection + companion nudges).
The system prompt lives in onboarding_prompt: a companion-invariant body plus a
beat-3/4 span rendered from the assigned companion's content row.
"""

import logging
import time
from typing import Any

from livekit.agents import llm

from base_agent import BaseGameAgent
from check_tools import check
from movement_tools import move_player
from onboarding_background import OnboardingBackgroundProcess
from onboarding_prompt import build_onboarding_instructions
from onboarding_tools import advance_onboarding_beat
from query_tools import query_info
from scene_tools import enter_location
from session_data import SessionData
from session_tools import record_story_moment

logger = logging.getLogger("divineruin.onboarding")

ONBOARDING_TOOLS = [
    enter_location,
    query_info,
    move_player,
    check,
    record_story_moment,
    advance_onboarding_beat,
]


class OnboardingAgent(BaseGameAgent):
    """Guided onboarding agent for new players' first session.

    Drives a 5-beat scripted sequence: Arrival, Market, Companion Meeting,
    The Companion's Suggestion, First Destination. After beat 5, hands off to the
    exploration agent.

    companion_id is the player's ASSIGNED companion — a pure function of their archetype via
    select_companion_for_archetype, resolved by whichever site constructs this agent (the
    creation handoff or a mid-onboarding reconnect). None renders beats 3-4 without a named
    companion; see onboarding_prompt._unassigned_span.
    """

    def __init__(self, onboarding_beat: int = 1, chat_ctx: Any = None, companion_id: str | None = None) -> None:
        super().__init__(
            instructions=build_onboarding_instructions(onboarding_beat, companion_id),
            tools=ONBOARDING_TOOLS,
            chat_ctx=chat_ctx,
        )
        self._onboarding_beat = onboarding_beat
        self._background: OnboardingBackgroundProcess | None = None

    async def on_enter(self) -> None:
        await super().on_enter()
        sd: SessionData = self.session.userdata
        sd.onboarding_beat = self._onboarding_beat
        self._background = OnboardingBackgroundProcess(session=self.session, session_data=sd)
        self._background.start()

        logger.info(
            "OnboardingAgent entered session for player %s at beat %d",
            sd.player_id,
            self._onboarding_beat,
        )

        if self._onboarding_beat == 1:
            # First beat — trigger arrival narration
            self.session.generate_reply(
                instructions=(
                    "Call enter_location with 'accord_market_square' to get scene context. "
                    "Then deliver Beat 1: the Arrival narration. "
                    "Do NOT say you are looking anything up. Just BE the narrator. "
                    "The mist clears, the player materializes in the market square. Evening. "
                    "One vivid sensory detail. End with an invitation to look around."
                ),
            )

    async def on_user_turn_completed(self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage) -> None:
        sd: SessionData = self.session.userdata
        sd.last_player_speech_time = time.time()

    async def on_exit(self) -> None:
        if self._background:
            await self._background.stop()
        sd: SessionData = self.session.userdata
        logger.info("OnboardingAgent exiting at beat %s", sd.onboarding_beat)
        await super().on_exit()
