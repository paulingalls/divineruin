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
        assert "enter_mode" not in tool_names
        assert "end_session" not in tool_names
        assert "award_xp" not in tool_names
        assert "end_combat" not in tool_names
        assert "update_quest" not in tool_names

    def test_tool_list_has_city_query_tools(self):
        """OnboardingAgent should have city query tools for exploration."""
        from onboarding_agent import ONBOARDING_TOOLS

        tool_names = {t.__name__ for t in ONBOARDING_TOOLS}
        assert "enter_location" in tool_names
        assert "query_info" in tool_names
        assert "move_player" in tool_names

    @pytest.mark.asyncio
    async def test_instructions_contain_beat_sequence(self):
        """System prompt should reference all 5 beats."""
        from onboarding_agent import OnboardingAgent

        agent = OnboardingAgent(onboarding_beat=1)
        instructions = agent._instructions
        assert "Arrival" in instructions or "arrival" in instructions
        assert "Market" in instructions or "market" in instructions
        assert "Companion" in instructions


class TestBeat34NamesTheAssignedCompanion:
    """AC1: beats 3-4 name and tag the player's OWN companion, not the module's Kael literal."""

    @pytest.mark.parametrize(
        "archetype,name,tag",
        [
            ("mage", "Kael", "COMPANION_KAEL"),
            ("warrior", "Lira", "COMPANION_LIRA"),
            ("cleric", "Tam", "COMPANION_TAM"),
            ("spy", "Sable", "COMPANION_SABLE"),
        ],
    )
    def test_beat_3_4_instructions_name_the_assigned_companion(self, archetype, name, tag):
        from companion_profiles import select_companion_for_archetype
        from onboarding_agent import OnboardingAgent

        agent = OnboardingAgent(onboarding_beat=3, companion_id=select_companion_for_archetype(archetype))
        instructions = agent._instructions
        assert name in instructions
        for other in {"Kael", "Lira", "Tam", "Sable"} - {name}:
            assert other not in instructions, f"{other} leaked into {name}'s prompt"

    def test_a_verbal_companion_is_tagged_for_ventriloquism(self):
        from onboarding_agent import OnboardingAgent

        agent = OnboardingAgent(onboarding_beat=3, companion_id="companion_lira")
        assert "[COMPANION_LIRA," in agent._instructions

    def test_a_non_verbal_companion_is_narrated_never_tagged(self):
        """Sable cannot self-introduce: a tagged line would send her to TTS she has no voice for."""
        from onboarding_agent import OnboardingAgent

        agent = OnboardingAgent(onboarding_beat=3, companion_id="companion_sable")
        assert "[COMPANION_SABLE," not in agent._instructions
        assert "narrate" in agent._instructions.lower()

    def test_an_unresolved_companion_renders_the_span_agnostically(self):
        """creation_tools swallows a failed selection deliberately; the character stays playable."""
        from onboarding_agent import OnboardingAgent

        instructions = OnboardingAgent(onboarding_beat=3, companion_id=None)._instructions
        for cname in ("Kael", "Lira", "Tam", "Sable"):
            assert cname not in instructions

    def test_no_module_level_per_companion_prompt_constants(self):
        """AC1's maintainability clause: the span renders from the profile, not four constants.

        Zero, not "at most one per constant": four constants that each name a single companion
        ARE the forbidden shape, so a per-constant budget passes the very defect it guards.
        And the modules scanned must include the one that now holds the prompt — the AC7 walker
        allowlists onboarding_prompt.py, so it is blind here.
        """
        import onboarding_agent
        import onboarding_prompt

        for module in (onboarding_agent, onboarding_prompt):
            for attr in dir(module):
                text = getattr(module, attr)
                if not attr.isupper() or not isinstance(text, str) or attr.startswith("__"):
                    continue
                named = [c for c in ("Kael", "Lira", "Tam", "Sable") if c in text]
                assert not named, f"{module.__name__}.{attr} names {named}"


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
