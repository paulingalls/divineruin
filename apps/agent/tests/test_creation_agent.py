"""Tests for CreationAgent — creation-only voice agent."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from base_agent import BaseGameAgent
from creation_prompts import CREATION_SYSTEM_PROMPT
from session_data import SessionData


class TestCreationAgentInit:
    """CreationAgent construction."""

    def test_extends_base_game_agent(self):
        from creation_agent import CreationAgent

        agent = CreationAgent()
        assert isinstance(agent, BaseGameAgent)

    def test_has_creation_system_prompt(self):
        from creation_agent import CreationAgent

        agent = CreationAgent()
        assert agent._instructions == CREATION_SYSTEM_PROMPT

    def test_has_creation_tools_only(self):
        from creation_agent import CREATION_TOOLS, CreationAgent

        agent = CreationAgent()
        assert list(agent._tools) == CREATION_TOOLS

    def test_no_gameplay_tools(self):
        from creation_agent import CreationAgent

        agent = CreationAgent()
        tool_names = {t.__name__ for t in agent._tools}
        assert "enter_location" not in tool_names
        assert "start_combat" not in tool_names
        assert "move_player" not in tool_names
        assert "end_session" not in tool_names

    def test_creation_tools_list_contents(self):
        from creation_agent import CREATION_TOOLS

        tool_names = {t.__name__ for t in CREATION_TOOLS}
        assert tool_names == {
            "push_creation_cards",
            "set_creation_choice",
            "finalize_character",
            "play_sound",
            "set_music_state",
        }

    def test_accepts_chat_ctx(self):
        from creation_agent import CreationAgent

        mock_ctx = MagicMock()
        CreationAgent(chat_ctx=mock_ctx)
        # Agent base class copies chat_ctx, so verify copy was called
        mock_ctx.copy.assert_called_once()


class TestCreationAgentOnEnter:
    """CreationAgent.on_enter pushes race cards and triggers initial reply."""

    @pytest.mark.asyncio
    async def test_on_enter_pushes_race_cards(self):
        from creation_agent import CreationAgent

        agent = CreationAgent()
        mock_session = MagicMock()
        mock_sd = SessionData(
            player_id="test_player",
            location_id="",
            room=MagicMock(),
        )
        mock_session.userdata = mock_sd

        with patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)):
            with patch("creation_agent.push_cards_to_client", new_callable=AsyncMock) as mock_push:
                await agent.on_enter()

                mock_push.assert_called_once_with("race", mock_sd.room, mock_sd.event_bus)

    @pytest.mark.asyncio
    async def test_on_enter_starts_card_tap_handler(self):
        from creation_agent import CreationAgent

        agent = CreationAgent()
        mock_session = MagicMock()
        mock_sd = SessionData(
            player_id="test_player",
            location_id="",
            room=MagicMock(),
        )
        mock_session.userdata = mock_sd

        with patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)):
            with patch("creation_agent.push_cards_to_client", new_callable=AsyncMock):
                with patch("creation_agent.CardTapHandler") as MockCTH:
                    mock_cth = MagicMock()
                    MockCTH.return_value = mock_cth
                    await agent.on_enter()

                    MockCTH.assert_called_once_with(room=mock_sd.room, session=mock_session, userdata=mock_sd)
                    mock_cth.start.assert_called_once()
                    assert agent._card_tap is mock_cth

    @pytest.mark.asyncio
    async def test_on_enter_generates_initial_reply(self):
        from creation_agent import CreationAgent

        agent = CreationAgent()
        mock_session = MagicMock()
        mock_sd = SessionData(
            player_id="test_player",
            location_id="",
            room=MagicMock(),
        )
        mock_session.userdata = mock_sd

        with patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)):
            with patch("creation_agent.push_cards_to_client", new_callable=AsyncMock):
                await agent.on_enter()

                mock_session.generate_reply.assert_called_once()
                call_kwargs = mock_session.generate_reply.call_args[1]
                assert "Awakening" in call_kwargs["instructions"]
                assert call_kwargs["tool_choice"] == "none"


class TestCreationAgentReadinessGate:
    """CreationAgent ignores stale STT turns until ready."""

    def test_not_ready_on_init(self):
        from creation_agent import CreationAgent

        agent = CreationAgent()
        assert agent._ready is False

    @pytest.mark.asyncio
    async def test_rejects_user_turn_before_ready(self):
        from livekit.agents import StopResponse

        from creation_agent import CreationAgent

        agent = CreationAgent()
        assert not agent._ready

        with pytest.raises(StopResponse):
            await agent.on_user_turn_completed(MagicMock(), MagicMock())

    @pytest.mark.asyncio
    async def test_allows_user_turn_after_ready(self):
        from creation_agent import CreationAgent

        agent = CreationAgent()
        agent._ready = True

        # Should not raise StopResponse
        await agent.on_user_turn_completed(MagicMock(), MagicMock())

    @pytest.mark.asyncio
    async def test_on_enter_sets_ready(self):
        from creation_agent import CreationAgent

        agent = CreationAgent()
        mock_session = MagicMock()
        mock_sd = SessionData(
            player_id="test_player",
            location_id="",
            room=MagicMock(),
        )
        mock_session.userdata = mock_sd

        with patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)):
            with patch("creation_agent.push_cards_to_client", new_callable=AsyncMock):
                await agent.on_enter()

        assert agent._ready is True


class TestCreationAgentOnExit:
    """CreationAgent.on_exit stops CardTapHandler."""

    @pytest.mark.asyncio
    async def test_on_exit_stops_card_tap_handler(self):
        from creation_agent import CreationAgent

        agent = CreationAgent()
        mock_cth = MagicMock()
        agent._card_tap = mock_cth
        agent._transcript = MagicMock()
        agent._transcript.log_path = "/tmp/test.log"

        mock_session = MagicMock()
        mock_sd = MagicMock()
        mock_sd.player_id = "test_player"
        mock_session.userdata = mock_sd

        with patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)):
            await agent.on_exit()

        mock_cth.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_exit_handles_no_card_tap(self):
        """on_exit should not error if CardTapHandler was never started."""
        from creation_agent import CreationAgent

        agent = CreationAgent()
        agent._card_tap = None
        agent._transcript = MagicMock()
        agent._transcript.log_path = "/tmp/test.log"

        mock_session = MagicMock()
        mock_sd = MagicMock()
        mock_sd.player_id = "test_player"
        mock_session.userdata = mock_sd

        with patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)):
            await agent.on_exit()  # Should not raise
