"""Tests for CityAgent — city/settlement gameplay agent."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from base_agent import BaseGameAgent
from prompts import COMBAT_PROMPT, VOICE_STYLE_PROMPT
from session_data import CompanionState
from tools import (
    end_combat,
    enter_location,
    move_player,
    query_location,
    query_npc,
    request_death_save,
    resolve_enemy_turn,
    start_combat,
    update_quest,
)


class TestCityAgentInheritance:
    """CityAgent must inherit BaseGameAgent for shared voice pipeline."""

    def test_inherits_base_game_agent(self):
        from city_agent import CityAgent

        agent = CityAgent()
        assert isinstance(agent, BaseGameAgent)

    def test_has_tts_node(self):
        from city_agent import CityAgent

        agent = CityAgent()
        assert agent.tts_node.__func__ is BaseGameAgent.tts_node

    def test_has_stt_node(self):
        from city_agent import CityAgent

        agent = CityAgent()
        assert agent.stt_node.__func__ is BaseGameAgent.stt_node

    def test_has_llm_node(self):
        from city_agent import CityAgent

        agent = CityAgent()
        assert agent.llm_node.__func__ is BaseGameAgent.llm_node


class TestCityAgentToolIsolation:
    """CityAgent has all non-combat tools + start_combat, but no combat-only tools."""

    def test_has_exploration_tools(self):
        from city_agent import CITY_TOOLS

        assert enter_location in CITY_TOOLS
        assert query_location in CITY_TOOLS
        assert query_npc in CITY_TOOLS

    def test_has_mutation_tools(self):
        from city_agent import CITY_TOOLS

        assert move_player in CITY_TOOLS
        assert update_quest in CITY_TOOLS

    def test_has_start_combat(self):
        from city_agent import CITY_TOOLS

        assert start_combat in CITY_TOOLS

    def test_no_combat_only_tools(self):
        from city_agent import CITY_TOOLS

        assert resolve_enemy_turn not in CITY_TOOLS
        assert request_death_save not in CITY_TOOLS
        assert end_combat not in CITY_TOOLS

    def test_tools_match_agent_instance(self):
        from city_agent import CITY_TOOLS, CityAgent

        agent = CityAgent()
        assert agent.tools == CITY_TOOLS


class TestCityAgentPrompt:
    """CityAgent prompt includes voice style but not combat rules."""

    def test_prompt_includes_voice_style(self):
        from city_agent import CityAgent

        agent = CityAgent()
        assert VOICE_STYLE_PROMPT in agent.instructions

    def test_prompt_excludes_combat(self):
        from city_agent import CityAgent

        agent = CityAgent()
        assert COMBAT_PROMPT not in agent.instructions

    def test_prompt_includes_location_context(self):
        from city_agent import CityAgent

        agent = CityAgent(initial_location="accord_market_square")
        assert "accord_market_square" in agent.instructions

    def test_prompt_includes_companion_when_provided(self):
        from city_agent import CityAgent

        companion = CompanionState(id="companion_kael", name="Kael")
        agent = CityAgent(initial_location="accord_market_square", companion=companion)
        assert "Kael" in agent.instructions


class TestCityAgentBackgroundProcess:
    """CityAgent manages BackgroundProcess in on_enter/on_exit."""

    @pytest.mark.asyncio
    async def test_on_enter_starts_background_process(self):
        from city_agent import CityAgent

        agent = CityAgent()
        mock_session = MagicMock()
        mock_sd = MagicMock()
        mock_session.userdata = mock_sd

        with patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)):
            with patch("gameplay_agent.BackgroundProcess") as MockBP:
                mock_bp = MagicMock()
                MockBP.return_value = mock_bp
                await agent.on_enter()

                MockBP.assert_called_once_with(agent=agent, session=mock_session, session_data=mock_sd)
                mock_bp.start.assert_called_once()
                assert agent._background is mock_bp

    @pytest.mark.asyncio
    async def test_on_exit_stops_background_process(self):
        from city_agent import CityAgent

        agent = CityAgent()
        agent._background = MagicMock()
        agent._background.stop = AsyncMock()
        agent._transcript = MagicMock()
        agent._transcript.log_path = "/tmp/test.log"

        mock_session = MagicMock()
        mock_sd = MagicMock()
        mock_sd.player_id = "player_1"
        mock_sd.session_id = "session_1"
        mock_session.userdata = mock_sd

        with patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)):
            with patch("gameplay_agent.generate_session_summary", new_callable=AsyncMock, return_value={}):
                with patch("gameplay_agent.publish_game_event", new_callable=AsyncMock):
                    with patch("gameplay_agent.db.save_session_summary", new_callable=AsyncMock):
                        await agent.on_exit()

        agent._background.stop.assert_awaited_once()


class TestCityAgentHotContext:
    """CityAgent builds hot context from SessionData caches."""

    def test_includes_location_and_time(self):
        from city_agent import CityAgent

        agent = CityAgent()
        mock_sd = MagicMock()
        mock_sd.location_id = "accord_market_square"
        mock_sd.world_time = "evening"
        mock_sd.cached_location_name = "Market Square"
        mock_sd.cached_quest_summaries = []
        mock_sd.cached_npc_names = []
        mock_sd.recent_events = []
        mock_sd.combat_state = None

        result = agent._build_hot_context(mock_sd)
        assert "[Context: Market Square, evening]" in result

    def test_includes_quests(self):
        from city_agent import CityAgent

        agent = CityAgent()
        mock_sd = MagicMock()
        mock_sd.location_id = "guild_hall"
        mock_sd.world_time = "day"
        mock_sd.cached_location_name = "Guild Hall"
        mock_sd.cached_quest_summaries = ["Find the Artifact: Search the ruins"]
        mock_sd.cached_npc_names = []
        mock_sd.recent_events = []
        mock_sd.combat_state = None

        result = agent._build_hot_context(mock_sd)
        assert "[Quests:" in result
        assert "Find the Artifact" in result

    def test_includes_npcs(self):
        from city_agent import CityAgent

        agent = CityAgent()
        mock_sd = MagicMock()
        mock_sd.location_id = "guild_hall"
        mock_sd.world_time = "evening"
        mock_sd.cached_location_name = "Guild Hall"
        mock_sd.cached_quest_summaries = []
        mock_sd.cached_npc_names = ["Guildmaster Torin"]
        mock_sd.recent_events = []
        mock_sd.combat_state = None

        result = agent._build_hot_context(mock_sd)
        assert "[NPCs nearby:" in result
        assert "Guildmaster Torin" in result

    def test_includes_recent_events_max_3(self):
        from city_agent import CityAgent

        agent = CityAgent()
        mock_sd = MagicMock()
        mock_sd.location_id = "town"
        mock_sd.world_time = "night"
        mock_sd.cached_location_name = "Town"
        mock_sd.cached_quest_summaries = []
        mock_sd.cached_npc_names = []
        mock_sd.recent_events = ["A", "B", "C", "D"]
        mock_sd.combat_state = None

        result = agent._build_hot_context(mock_sd)
        assert "[Recent:" in result
        assert "D" in result
        assert "A" not in result


class TestCityAgentTurnHandling:
    """CityAgent injects hot context and affect on user turns."""

    @pytest.mark.asyncio
    async def test_on_user_turn_completed_adds_hot_context(self):
        from city_agent import CityAgent

        agent = CityAgent()
        mock_turn_ctx = MagicMock()
        mock_message = MagicMock()
        mock_sd = MagicMock()
        mock_session = MagicMock()
        mock_session.userdata = mock_sd

        with patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)):
            with patch.object(agent, "_build_hot_context", return_value="[Context: Market]"):
                await agent.on_user_turn_completed(mock_turn_ctx, mock_message)

        mock_turn_ctx.add_message.assert_called_once_with(role="assistant", content="[Context: Market]")

    @pytest.mark.asyncio
    async def test_on_agent_turn_completed_delayed_close(self):
        from city_agent import CityAgent

        agent = CityAgent()
        mock_turn_ctx = MagicMock()
        mock_message = MagicMock()
        mock_sd = MagicMock()
        mock_sd.ending_requested = True
        mock_session = MagicMock()
        mock_session.userdata = mock_sd
        mock_session.aclose = AsyncMock()

        with patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)):
            with patch.object(agent, "_fire_and_forget") as mock_faf:
                await agent.on_agent_turn_completed(mock_turn_ctx, mock_message)
                assert agent._close_scheduled is True
                mock_faf.assert_called_once()
