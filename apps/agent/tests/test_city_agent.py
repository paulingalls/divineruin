"""Tests for CityAgent — city/settlement gameplay agent."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from base_agent import BaseGameAgent
from city_agent import CITY_TOOLS, CityAgent
from prompts import COMBAT_PROMPT, VOICE_STYLE_PROMPT, build_system_prompt
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


class TestCityAgentConfig:
    def test_inherits_base_game_agent(self):
        assert issubclass(CityAgent, BaseGameAgent)

    def test_agent_type_is_city(self):
        assert CityAgent._agent_type == "city"


class TestCityAgentToolIsolation:
    def test_has_exploration_tools(self):
        assert enter_location in CITY_TOOLS
        assert query_location in CITY_TOOLS
        assert query_npc in CITY_TOOLS

    def test_has_mutation_tools(self):
        assert move_player in CITY_TOOLS
        assert update_quest in CITY_TOOLS

    def test_has_start_combat(self):
        assert start_combat in CITY_TOOLS

    def test_no_combat_only_tools(self):
        assert resolve_enemy_turn not in CITY_TOOLS
        assert request_death_save not in CITY_TOOLS
        assert end_combat not in CITY_TOOLS


class TestCityAgentPrompt:
    def test_prompt_includes_voice_style(self):
        prompt = build_system_prompt("accord_market_square", region_type="city")
        assert VOICE_STYLE_PROMPT in prompt

    def test_prompt_excludes_combat(self):
        prompt = build_system_prompt("accord_market_square", region_type="city")
        assert COMBAT_PROMPT not in prompt

    def test_prompt_includes_location_context(self):
        prompt = build_system_prompt("accord_market_square", region_type="city")
        assert "accord_market_square" in prompt

    def test_prompt_includes_companion_when_provided(self):
        companion = CompanionState(id="companion_kael", name="Kael")
        prompt = build_system_prompt("accord_market_square", companion=companion, region_type="city")
        assert "Kael" in prompt


class TestGameplayAgentBehavior:
    """Test GameplayAgent lifecycle and hot context via CityAgent instance."""

    @pytest.mark.asyncio
    async def test_on_enter_starts_background_process(self):
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

    def test_hot_context_includes_location_and_time(self):
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

    def test_hot_context_includes_quests(self):
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

    def test_hot_context_includes_npcs(self):
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

    def test_hot_context_recent_events_max_3(self):
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

    @pytest.mark.asyncio
    async def test_on_user_turn_completed_adds_hot_context(self):
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
        agent = CityAgent()
        mock_turn_ctx = MagicMock()
        mock_message = MagicMock()
        mock_sd = MagicMock()
        mock_sd.ending_requested = True
        mock_session = MagicMock()
        mock_session.userdata = mock_sd

        def _consume_coro(coro):
            """Close the coroutine to prevent unawaited warnings."""
            coro.close()

        with patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)):
            with patch.object(agent, "_fire_and_forget", side_effect=_consume_coro) as mock_faf:
                await agent.on_agent_turn_completed(mock_turn_ctx, mock_message)
                assert agent._close_scheduled is True
                mock_faf.assert_called_once()
