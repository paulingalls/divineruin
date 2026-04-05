"""CreationAgent — guides character creation with voice.

Sonnet model, creation-only tools, CREATION_SYSTEM_PROMPT.
Manages CardTapHandler lifecycle for client card interactions.
"""

import logging

from base_agent import BaseGameAgent
from card_tap_handler import CardTapHandler
from creation_prompts import CREATION_SYSTEM_PROMPT
from creation_tools import finalize_character, push_cards_to_client, push_creation_cards, set_creation_choice
from session_data import SessionData
from tools import play_sound, set_music_state

logger = logging.getLogger("divineruin.creation_agent")

CREATION_TOOLS = [push_creation_cards, set_creation_choice, finalize_character, play_sound, set_music_state]


class CreationAgent(BaseGameAgent):
    """Creation-only agent with Sonnet model and creation tools.

    Guides players through character creation: Awakening (race),
    Calling (class), Devotion (deity), Identity (name/backstory), Finalize.
    """

    def __init__(self, chat_ctx=None) -> None:
        super().__init__(
            instructions=CREATION_SYSTEM_PROMPT,
            tools=CREATION_TOOLS,
            chat_ctx=chat_ctx,
        )
        self._card_tap: CardTapHandler | None = None
        self._ready = False

    async def on_enter(self) -> None:
        await super().on_enter()
        sd: SessionData = self.session.userdata
        logger.info("CreationAgent entered session for player %s", sd.player_id)

        # Start listening for card taps from client
        assert sd.room is not None  # room is set before agent enters
        self._card_tap = CardTapHandler(room=sd.room, session=self.session, userdata=sd)
        self._card_tap.start()

        # Push initial race cards so they're on screen
        await push_cards_to_client("race", sd.room, sd.event_bus)

        # Trigger opening narration
        self.session.generate_reply(
            instructions=(
                "The prologue has finished. Begin the Awakening phase. "
                "The race cards are already visible to the player — "
                "do NOT call push_creation_cards. "
                "Ask the player about their race using the sensory approach "
                "from your instructions."
            ),
            tool_choice="none",
        )
        self._ready = True

    async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
        if not self._ready:
            from livekit.agents import StopResponse

            raise StopResponse()

    async def on_exit(self) -> None:
        if self._card_tap:
            self._card_tap.stop()
        await super().on_exit()
