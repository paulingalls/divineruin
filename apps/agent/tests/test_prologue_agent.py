"""Tests for PrologueAgent — no-LLM audio-only agent."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from session_data import SessionData


def _mock_session_property(mock_session):
    """Patch Agent.session property to return mock_session."""
    return patch.object(
        type(mock_session._agent),
        "session",
        new_callable=lambda: property(lambda self: mock_session),
    )


def _make_prologue_agent_with_session():
    """Create a PrologueAgent with a mocked session."""
    from prologue_agent import PrologueAgent

    agent = PrologueAgent()
    mock_session = MagicMock()
    mock_session._agent = agent
    mock_session.userdata = SessionData(
        player_id="test_player",
        location_id="",
        room=MagicMock(),
    )
    return agent, mock_session


class TestPrologueAgentInit:
    """PrologueAgent construction."""

    def test_has_no_tools(self):
        from prologue_agent import PrologueAgent

        agent = PrologueAgent()
        assert agent._tools == [] or len(list(agent._tools)) == 0

    def test_has_empty_instructions(self):
        from prologue_agent import PrologueAgent

        agent = PrologueAgent()
        assert agent._instructions == ""


class TestPrologueAgentOnEnter:
    """PrologueAgent.on_enter plays prologue and hands off to CreationAgent."""

    @pytest.mark.asyncio
    async def test_on_enter_plays_prologue_and_hands_off(self):
        agent, mock_session = _make_prologue_agent_with_session()

        with (
            _mock_session_property(mock_session),
            patch("prologue.play_prologue", new_callable=AsyncMock, return_value=False) as mock_play,
        ):
            await agent.on_enter()

            # Verify prologue was played
            mock_play.assert_called_once_with(mock_session, mock_session.userdata.room)

            # Verify handoff to CreationAgent
            mock_session.update_agent.assert_called_once()
            from creation_agent import CreationAgent

            handoff_agent = mock_session.update_agent.call_args[0][0]
            assert isinstance(handoff_agent, CreationAgent)

    @pytest.mark.asyncio
    async def test_on_enter_hands_off_on_skip(self):
        """When player interrupts prologue, still hands off to CreationAgent."""
        agent, mock_session = _make_prologue_agent_with_session()

        with (
            _mock_session_property(mock_session),
            patch("prologue.play_prologue", new_callable=AsyncMock, return_value=True),
        ):
            await agent.on_enter()

            mock_session.update_agent.assert_called_once()
            from creation_agent import CreationAgent

            handoff_agent = mock_session.update_agent.call_args[0][0]
            assert isinstance(handoff_agent, CreationAgent)


class TestPrologueAgentAutoReply:
    """PrologueAgent never auto-replies during prologue."""

    @pytest.mark.asyncio
    async def test_on_user_turn_completed_raises_stop_response(self):
        from livekit.agents import StopResponse

        from prologue_agent import PrologueAgent

        agent = PrologueAgent()

        with pytest.raises(StopResponse):
            await agent.on_user_turn_completed(MagicMock(), MagicMock())
