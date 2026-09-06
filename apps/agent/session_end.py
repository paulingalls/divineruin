"""Session end: the recap the player hears, fired once — when the SESSION closes.

Not on an agent's ``on_exit``. That runs on every mode handoff (``AgentActivity.drain``
awaits it, agent_activity.py:919-932), so a SESSION_END published there reached the client
on the way into every fight and flipped it to the end-of-session summary screen
(``apps/mobile/src/audio/game-event-handler.ts:264-291``). Debt 2009d9ef.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import db_mutations
import event_types as E
from game_events import publish_game_event
from session_summary import generate_session_summary

if TYPE_CHECKING:
    from session_data import SessionData

logger = logging.getLogger("divineruin.session_end")


async def run_session_end(sd: SessionData) -> None:
    """Generate the session summary, publish it to the client, and store the row.

    Every input is session-scoped, read off ``SessionData``: an agent instance knows only
    its own slice of the session, and the recap covers the whole of it.
    """
    payload = await generate_session_summary(sd, sd.transcript_path, sd.session_start_time)

    results = await asyncio.gather(
        publish_game_event(sd.room, E.SESSION_END, payload, sd.event_bus),
        db_mutations.save_session_summary(sd.player_id, sd.session_id, payload),
        return_exceptions=True,
    )
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            labels = ("publish session_end", "save session summary")
            logger.exception("Failed to %s", labels[i], exc_info=result)
