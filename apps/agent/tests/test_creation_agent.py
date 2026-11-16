from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from base_agent import BaseGameAgent
from session_data import CreationState, SessionData


class TestCreationAgentInit:
    def test_extends_base_game_agent(self):
        from creation_agent import CreationAgent

        agent = CreationAgent()
        assert isinstance(agent, BaseGameAgent)

    def test_accepts_chat_ctx(self):
        from creation_agent import CreationAgent

        mock_ctx = MagicMock()
        CreationAgent(chat_ctx=mock_ctx)
        mock_ctx.copy.assert_called_once()


class TestCreationAgentOnEnter:
    @pytest.mark.asyncio
    async def test_on_enter_starts_card_tap_handler(self):
        from creation_agent import CreationAgent

        agent = CreationAgent()
        mock_session = MagicMock()
        mock_sd = SessionData(
            player_id="test_player",
            location_id="",
            creation_state=CreationState(),
            room=MagicMock(),
        )
        mock_session.userdata = mock_sd

        with patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)):
            with patch("creation_agent.push_cards_to_client", new_callable=AsyncMock):
                with patch("creation_agent.push_creation_music", new_callable=AsyncMock):
                    with patch("creation_agent.CardTapHandler") as MockCTH:
                        mock_cth = MagicMock()
                        MockCTH.return_value = mock_cth
                        await agent.on_enter()

                        MockCTH.assert_called_once_with(room=mock_sd.room, session=mock_session, userdata=mock_sd)
                        mock_cth.start.assert_called_once()
                        assert agent._card_tap is mock_cth


class TestCreationAgentReadinessGate:
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

        await agent.on_user_turn_completed(MagicMock(), MagicMock())

    @pytest.mark.asyncio
    async def test_on_enter_sets_ready(self):
        from creation_agent import CreationAgent

        agent = CreationAgent()
        mock_session = MagicMock()
        mock_sd = SessionData(
            player_id="test_player",
            location_id="",
            creation_state=CreationState(),
            room=MagicMock(),
        )
        mock_session.userdata = mock_sd

        with patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)):
            with patch("creation_agent.push_cards_to_client", new_callable=AsyncMock):
                with patch("creation_agent.push_creation_music", new_callable=AsyncMock):
                    await agent.on_enter()

        assert agent._ready is True


class TestCreationAgentOnExit:
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
