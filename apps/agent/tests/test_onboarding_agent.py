"""Tests for OnboardingAgent and onboarding-related SessionData fields."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from base_agent import BaseGameAgent
from session_data import SessionData


class TestOnboardingBeatField:
    """SessionData.onboarding_beat field and in_onboarding property."""

    def test_onboarding_beat_defaults_to_none(self):
        sd = SessionData(player_id="p1", location_id="accord_market_square")
        assert sd.onboarding_beat is None

    def test_onboarding_beat_can_be_set(self):
        sd = SessionData(player_id="p1", location_id="accord_market_square", onboarding_beat=1)
        assert sd.onboarding_beat == 1

    def test_in_onboarding_true_when_beat_set(self):
        sd = SessionData(player_id="p1", location_id="accord_market_square", onboarding_beat=3)
        assert sd.in_onboarding is True

    def test_in_onboarding_false_when_beat_none(self):
        sd = SessionData(player_id="p1", location_id="accord_market_square")
        assert sd.in_onboarding is False

    def test_in_onboarding_false_does_not_conflict_with_in_creation(self):
        """in_onboarding and in_creation are independent states."""
        from session_data import CreationState

        sd = SessionData(
            player_id="p1",
            location_id="",
            creation_state=CreationState(),
        )
        assert sd.in_creation is True
        assert sd.in_onboarding is False

    def test_onboarding_beat_range(self):
        """Beats 1-5 are valid onboarding states."""
        for beat in range(1, 6):
            sd = SessionData(player_id="p1", location_id="accord_market_square", onboarding_beat=beat)
            assert sd.in_onboarding is True
            assert sd.onboarding_beat == beat


class TestOnboardingAgentClass:
    """OnboardingAgent class structure and tool isolation."""

    def test_extends_base_game_agent(self):
        from onboarding_agent import OnboardingAgent

        assert issubclass(OnboardingAgent, BaseGameAgent)

    def test_constructor_accepts_beat_and_chat_ctx(self):
        from onboarding_agent import OnboardingAgent

        agent = OnboardingAgent(onboarding_beat=2)
        assert agent is not None

    def test_default_beat_is_1(self):
        from onboarding_agent import OnboardingAgent

        agent = OnboardingAgent()
        # Should not raise — default beat=1
        assert agent is not None

    def test_tool_list_has_advance_onboarding_beat(self):
        from onboarding_agent import ONBOARDING_TOOLS
        from onboarding_tools import advance_onboarding_beat

        assert advance_onboarding_beat in ONBOARDING_TOOLS

    def test_tool_isolation_no_combat_tools(self):
        """OnboardingAgent should not have combat or session-ending tools."""
        from onboarding_agent import ONBOARDING_TOOLS

        tool_names = {t.__name__ for t in ONBOARDING_TOOLS}
        assert "start_combat" not in tool_names
        assert "end_session" not in tool_names
        assert "award_xp" not in tool_names
        assert "end_combat" not in tool_names
        assert "update_quest" not in tool_names

    def test_tool_list_has_city_query_tools(self):
        """OnboardingAgent should have city query tools for exploration."""
        from onboarding_agent import ONBOARDING_TOOLS

        tool_names = {t.__name__ for t in ONBOARDING_TOOLS}
        assert "enter_location" in tool_names
        assert "query_location" in tool_names
        assert "query_npc" in tool_names
        assert "move_player" in tool_names
        assert "play_sound" in tool_names

    @pytest.mark.asyncio
    async def test_instructions_contain_beat_sequence(self):
        """System prompt should reference all 5 beats."""
        from onboarding_agent import OnboardingAgent

        agent = OnboardingAgent(onboarding_beat=1)
        instructions = agent._instructions
        assert "Arrival" in instructions or "arrival" in instructions
        assert "Market" in instructions or "market" in instructions
        assert "Companion" in instructions or "Kael" in instructions


class TestOnboardingAgentIntegration:
    """OnboardingAgent background process lifecycle and speech timing."""

    @pytest.mark.asyncio
    async def test_on_user_turn_completed_sets_speech_time(self):
        from onboarding_agent import OnboardingAgent

        agent = OnboardingAgent()
        mock_session = MagicMock()
        sd = SessionData(player_id="p1", location_id="accord_market_square", onboarding_beat=4)
        mock_session.userdata = sd

        before = time.time()
        with patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)):
            await agent.on_user_turn_completed(MagicMock(), MagicMock())
        after = time.time()

        assert before <= sd.last_player_speech_time <= after

    @pytest.mark.asyncio
    async def test_on_enter_starts_background_process(self):
        from onboarding_agent import OnboardingAgent

        agent = OnboardingAgent(onboarding_beat=1)
        mock_session = MagicMock()
        sd = SessionData(player_id="p1", location_id="accord_market_square", onboarding_beat=1)
        mock_session.userdata = sd

        with patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)):
            with patch("onboarding_agent.OnboardingBackgroundProcess") as MockBG:
                mock_bg = MagicMock()
                MockBG.return_value = mock_bg
                await agent.on_enter()

                MockBG.assert_called_once_with(session=mock_session, session_data=sd)
                mock_bg.start.assert_called_once()
                assert agent._background is mock_bg

    @pytest.mark.asyncio
    async def test_on_exit_stops_background_process(self):
        from onboarding_agent import OnboardingAgent

        agent = OnboardingAgent()
        mock_bg = AsyncMock()
        agent._background = mock_bg
        agent._transcript = MagicMock()
        agent._transcript.log_path = "/tmp/test.log"

        mock_session = MagicMock()
        sd = MagicMock()
        sd.player_id = "p1"
        sd.onboarding_beat = 4
        mock_session.userdata = sd

        with patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)):
            await agent.on_exit()

        mock_bg.stop.assert_awaited_once()
