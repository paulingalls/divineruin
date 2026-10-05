import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents import Agent

from base_agent import BaseGameAgent
from session_data import SessionData


def _instructions_text(agent: Agent) -> str:
    instructions = agent._instructions
    assert isinstance(instructions, str)
    return instructions


class TestOnboardingBeatField:
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
        from session_data import CreationState

        sd = SessionData(
            player_id="p1",
            location_id="",
            creation_state=CreationState(),
        )
        assert sd.in_creation is True
        assert sd.in_onboarding is False

    def test_onboarding_beat_range(self):
        for beat in range(1, 6):
            sd = SessionData(player_id="p1", location_id="accord_market_square", onboarding_beat=beat)
            assert sd.in_onboarding is True
            assert sd.onboarding_beat == beat


class TestOnboardingAgentClass:
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
        assert agent is not None

    def test_tool_list_has_advance_onboarding_beat(self):
        from onboarding_agent import ONBOARDING_TOOLS
        from onboarding_tools import advance_onboarding_beat

        assert advance_onboarding_beat in ONBOARDING_TOOLS

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
        assert "move_player" in tool_names

    @pytest.mark.asyncio
    async def test_instructions_contain_beat_sequence(self):
        from onboarding_agent import OnboardingAgent

        agent = OnboardingAgent(onboarding_beat=1)
        instructions = _instructions_text(agent)
        assert "Arrival" in instructions or "arrival" in instructions
        assert "Market" in instructions or "market" in instructions
        assert "Companion" in instructions


class TestBeat34NamesTheAssignedCompanion:
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
        instructions = _instructions_text(agent)
        assert name in instructions
        for other in {"Kael", "Lira", "Tam", "Sable"} - {name}:
            assert other not in instructions, f"{other} leaked into {name}'s prompt"

    @pytest.mark.parametrize("archetype", ["mage", "warrior", "cleric", "spy"])
    def test_beats_3_4_render_that_companions_authored_vignette(self, archetype):
        """The profile must surface text, not merely duplicate it inside tests."""
        from companion_profiles import get_companion_profile, select_companion_for_archetype
        from onboarding_agent import OnboardingAgent

        companion_id = select_companion_for_archetype(archetype)
        c = get_companion_profile(companion_id)
        instructions = _instructions_text(OnboardingAgent(onboarding_beat=3, companion_id=companion_id))
        assert c.onboarding_meeting in instructions
        assert c.onboarding_suggestion in instructions

    @pytest.mark.parametrize("archetype", ["mage", "warrior", "cleric", "spy", None])
    def test_beat_3_4_scaffolding_survives_the_authored_prose(self, archetype):
        """Scene beat markers belong to authored scenes rather than a parallel module inventory."""
        from companion_profiles import select_companion_for_archetype
        from onboarding_agent import OnboardingAgent

        companion_id = select_companion_for_archetype(archetype) if archetype else None
        instructions = _instructions_text(OnboardingAgent(onboarding_beat=3, companion_id=companion_id))
        assert "### Beat 3 — Companion Meeting" in instructions
        assert "### Beat 4 — The Companion's Suggestion" in instructions
        assert "(this initializes the companion)" in instructions
        span = instructions.split("### Beat 3 — Companion Meeting")[1].split("### Beat 5")[0]
        assert span.count("**Complete when:**") == 2
        assert span.count("advance_onboarding_beat") == 2

    def test_a_verbal_companion_is_tagged_for_ventriloquism(self):
        from onboarding_agent import OnboardingAgent

        agent = OnboardingAgent(onboarding_beat=3, companion_id="companion_lira")
        assert "[COMPANION_LIRA," in _instructions_text(agent)

    def test_a_non_verbal_companion_is_narrated_never_tagged(self):
        """Nonverbal characters must not be sent to speech synthesis."""
        from onboarding_agent import OnboardingAgent

        agent = OnboardingAgent(onboarding_beat=3, companion_id="companion_sable")
        instructions = _instructions_text(agent)
        assert "[COMPANION_SABLE," not in instructions
        assert "narrate" in instructions.lower()

    def test_an_unresolved_companion_renders_the_span_agnostically(self):
        """A swallowed selector failure can hide a missing playable companion."""
        from onboarding_agent import OnboardingAgent

        instructions = _instructions_text(OnboardingAgent(onboarding_beat=3, companion_id=None))
        for cname in ("Kael", "Lira", "Tam", "Sable"):
            assert cname not in instructions

    def test_no_module_level_per_companion_prompt_constants(self):
        """Companion identity must come from the assigned profile rather than fixed constants."""
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
    async def test_reconnect_on_enter_publishes_session_init_before_background(self):
        from onboarding_agent import OnboardingAgent

        agent = OnboardingAgent(onboarding_beat=3, publish_session_init=True)
        mock_session = MagicMock()
        sd = SessionData(player_id="p1", location_id="accord_market_square", onboarding_beat=3)
        mock_session.userdata = sd
        order = []

        with patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)):
            with (
                patch("onboarding_agent.db_session_queries.get_session_init_payload", new_callable=AsyncMock) as get,
                patch("onboarding_agent.publish_game_event", new_callable=AsyncMock) as publish,
                patch("onboarding_agent.OnboardingBackgroundProcess") as MockBG,
            ):
                mock_bg = MagicMock()
                MockBG.return_value = mock_bg
                publish.side_effect = lambda *_args: order.append("session_init")
                mock_bg.start.side_effect = lambda: order.append("background")
                await agent.on_enter()

                get.assert_awaited_once_with("p1")
                publish.assert_awaited_once_with(sd.room, "session_init", get.return_value, sd.event_bus)
                MockBG.assert_called_once_with(session=mock_session, session_data=sd)
                mock_bg.start.assert_called_once()
                assert agent._background is mock_bg
                assert order == ["session_init", "background"]

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
