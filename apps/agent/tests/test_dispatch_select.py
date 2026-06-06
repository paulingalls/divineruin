"""DispatchAgent select + specialization-tap wiring (M7 story-004).

Leveling also happens mid-training in the dispatch context, so the dispatch agent must
expose the generic ``select`` verb AND host the L5 ``SpecializationTapHandler`` — the
same consumer the exploration agents run (story-008) — so an L5 fork resolves (by HUD
tap or DM voice) without leaving dispatch. Closes debt 15da0e89fa97.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from base_agent import BaseGameAgent
from choice_tools import select
from dispatch_agent import DISPATCH_TOOLS, DispatchAgent
from session_data import SessionData


def _agent_with_session() -> tuple[DispatchAgent, MagicMock, SessionData]:
    agent = DispatchAgent()
    mock_session = MagicMock()
    sd = SessionData(player_id="test_player", location_id="", room=MagicMock())
    mock_session.userdata = sd
    return agent, mock_session, sd


def test_dispatch_tools_include_select():
    """The DM can resolve a pending L5 choice from dispatch — select is in the tool list."""
    assert select in DISPATCH_TOOLS


class TestDispatchSpecializationTapWiring:
    @pytest.mark.asyncio
    async def test_on_enter_starts_specialization_tap_handler(self):
        agent, mock_session, sd = _agent_with_session()
        with (
            patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)),
            patch.object(BaseGameAgent, "on_enter", new_callable=AsyncMock),
            patch("dispatch_agent.start_specialization_tap") as mock_start,
        ):
            mock_handler = MagicMock()
            mock_start.return_value = mock_handler
            await agent.on_enter()

            mock_start.assert_called_once_with(sd.room, mock_session, sd)
            assert agent._spec_tap is mock_handler

    @pytest.mark.asyncio
    async def test_on_exit_stops_specialization_tap_handler(self):
        agent, mock_session, _ = _agent_with_session()
        mock_handler = MagicMock()
        agent._spec_tap = mock_handler
        with (
            patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)),
            patch.object(BaseGameAgent, "on_exit", new_callable=AsyncMock),
        ):
            await agent.on_exit()

        mock_handler.stop.assert_called_once()
