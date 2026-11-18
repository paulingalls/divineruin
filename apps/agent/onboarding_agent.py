"""Guided arrival, market exploration and companion meeting."""

import logging
import time
from typing import Any

from livekit.agents import llm

import db_session_queries
import event_types as E
from base_agent import BaseGameAgent
from check_tools import check
from game_events import publish_game_event
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
    check,
    record_story_moment,
    advance_onboarding_beat,
]


class OnboardingAgent(BaseGameAgent):
    """Three beats ending with the assigned companion's meeting and exploration handoff.

    companion_id is resolved from the persisted archetype at creation or reconnect.
    None stages an unnamed stranger until assignment succeeds.
    """

    def __init__(
        self,
        onboarding_beat: int = 1,
        chat_ctx: Any = None,
        companion_id: str | None = None,
        *,
        publish_session_init: bool = False,
    ) -> None:
        super().__init__(
            instructions=build_onboarding_instructions(onboarding_beat, companion_id),
            tools=ONBOARDING_TOOLS,
            chat_ctx=chat_ctx,
        )
        self._onboarding_beat = onboarding_beat
        self._publish_session_init_on_enter = publish_session_init

    async def _enter(self) -> None:
        await super()._enter()
        sd: SessionData = self.session.userdata
        sd.onboarding_beat = self._onboarding_beat
        if self._publish_session_init_on_enter:
            try:
                payload = await db_session_queries.get_session_init_payload(sd.player_id)
                await publish_game_event(
                    sd.room, E.SESSION_INIT, payload, sd.event_bus, destination_identities=[sd.player_id]
                )
            except Exception:
                logger.exception("Failed to publish session_init after onboarding reconnect")

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
