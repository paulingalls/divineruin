import time
from unittest.mock import MagicMock, patch

import pytest

from session_data import SessionData


class TestOnboardingBeatField:
    def test_in_onboarding_true_when_beat_set(self):
        sd = SessionData(player_id="p1", location_id="accord_market_square", onboarding_beat=3)
        assert sd.in_onboarding is True

    def test_in_onboarding_false_when_beat_none(self):
        sd = SessionData(player_id="p1", location_id="accord_market_square")
        assert sd.in_onboarding is False

    def test_in_onboarding_false_does_not_conflict_with_in_creation(self):
        from session_data import CreationState

        sd = SessionData(
            player_id="p1",
            location_id="",
            creation_state=CreationState(),
        )
        assert sd.in_creation is True
        assert sd.in_onboarding is False


class TestOnboardingAgentClass:
    def test_tool_isolation_no_combat_tools(self):
        from onboarding_agent import ONBOARDING_TOOLS

        tool_names = {t.__name__ for t in ONBOARDING_TOOLS}
        assert "enter_mode" not in tool_names
        assert "end_session" not in tool_names
        assert "award_xp" not in tool_names
        assert "end_combat" not in tool_names
        assert "update_quest" not in tool_names

    def test_tool_list_has_city_query_tools(self):
        from onboarding_agent import ONBOARDING_TOOLS

        tool_names = {t.__name__ for t in ONBOARDING_TOOLS}
        assert "enter_location" in tool_names
        assert "query_info" in tool_names


class TestOnboardingAgentIntegration:
    @pytest.mark.asyncio
    async def test_on_user_turn_completed_sets_speech_time(self):
        from onboarding_agent import OnboardingAgent

        agent = OnboardingAgent()
        mock_session = MagicMock()
        sd = SessionData(player_id="p1", location_id="accord_market_square", onboarding_beat=3)
        mock_session.userdata = sd

        before = time.time()
        with patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)):
            await agent.on_user_turn_completed(MagicMock(), MagicMock())
        after = time.time()

        assert before <= sd.last_player_speech_time <= after
