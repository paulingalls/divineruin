"""The session's END — the summary the player hears, fired when the SESSION closes.

Not when an agent exits: an agent's ``on_exit`` runs on every mode handoff
(``AgentActivity.drain`` awaits it, agent_activity.py:919-932), so session-scoped work
placed there fires on the way into every fight.
"""

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents import AgentSession

from exploration_agent import ExplorationAgent
from session_data import SessionData


@contextlib.contextmanager
def _quiet_agent():
    """Silence the exploration agent's I/O — DB, data channel, HUD tap, warm loop."""
    with (
        patch("exploration_agent.start_specialization_tap"),
        patch("exploration_agent.BackgroundProcess"),
        patch("exploration_agent.db_session_queries.get_session_init_payload", new_callable=AsyncMock),
        patch("exploration_agent.publish_game_event", new_callable=AsyncMock),
        patch("exploration_agent.generate_session_summary", new_callable=AsyncMock, return_value={}),
        patch("exploration_agent.db_mutations.save_session_summary", new_callable=AsyncMock),
    ):
        yield


class TestEndSessionReachesTheCloseEmit:
    """``end_session`` is the only production path that closes the session from inside the
    agent, and every other guard in this file produces the close event by hand. If this path
    never reaches ``emit("close", ...)``, those guards certify a handler nothing calls.

    Real AgentSession, real AgentActivity, real ExplorationAgent (constraint 9): the question
    is whether the VENDOR's shutdown ordering — ``aclose`` -> ``activity.drain()`` -> our
    ``on_exit`` -> ``emit("close")`` (agent_session.py:1025-1058) — survives what our
    ``on_exit`` does to the task that is driving that very ``aclose``.
    """

    @pytest.mark.asyncio
    async def test_end_session_closes_the_session(self):
        sd = SessionData(player_id="player_1", location_id="accord_guild_hall")
        session = AgentSession(max_tool_steps=5, userdata=sd)
        closed = asyncio.Event()
        session.on("close", lambda _ev: closed.set())
        agent = ExplorationAgent()

        with _quiet_agent(), patch("exploration_agent.asyncio.sleep", new_callable=AsyncMock):
            await session.start(agent)
            sd.ending_requested = True
            await agent.on_agent_turn_completed(MagicMock(), MagicMock())
            await asyncio.wait_for(closed.wait(), timeout=5.0)
