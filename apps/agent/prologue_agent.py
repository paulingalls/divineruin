"""PrologueAgent — no-LLM audio-only agent for new player prologue.

Plays the prologue narration and listens for voice activity as a skip signal.
Programmatic handoff to CreationAgent on completion or skip.
"""

import logging

from livekit.agents import Agent

from session_data import SessionData

logger = logging.getLogger("divineruin.prologue_agent")


class PrologueAgent(Agent):
    """Audio-only agent that plays the prologue narration.

    No LLM, no tools. Detects player voice as skip signal.
    Hands off to CreationAgent when prologue finishes or is skipped.
    """

    def __init__(self) -> None:
        super().__init__(instructions="")

    async def on_enter(self) -> None:
        from prologue import play_prologue

        sd: SessionData = self.session.userdata
        logger.info("PrologueAgent entered session for player %s", sd.player_id)

        await play_prologue(self.session, sd.room)

        # Programmatic handoff — prologue complete or skipped
        from creation_agent import CreationAgent

        logger.info("Prologue done, handing off to CreationAgent")
        self.session.update_agent(CreationAgent())

    async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
        from livekit.agents import StopResponse

        raise StopResponse()  # Never auto-reply during prologue
