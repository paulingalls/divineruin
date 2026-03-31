"""Tests for WildernessAgent — wilderness/travel gameplay agent."""

from base_agent import BaseGameAgent
from prompts import COMBAT_PROMPT, VOICE_STYLE_PROMPT, WILDERNESS_PROMPT
from tools import (
    discover_hidden_element,
    end_combat,
    enter_location,
    move_player,
    query_inventory,
    query_location,
    query_lore,
    record_story_moment,
    request_skill_check,
    resolve_enemy_turn,
    roll_dice,
    start_combat,
    update_quest,
)


class TestWildernessAgentInheritance:
    def test_inherits_base_game_agent(self):
        from wilderness_agent import WildernessAgent

        agent = WildernessAgent()
        assert isinstance(agent, BaseGameAgent)

    def test_agent_type_is_wilderness(self):
        from wilderness_agent import WildernessAgent

        agent = WildernessAgent()
        assert agent._agent_type == "wilderness"

    def test_has_tts_node(self):
        from wilderness_agent import WildernessAgent

        agent = WildernessAgent()
        assert agent.tts_node.__func__ is BaseGameAgent.tts_node

    def test_has_stt_node(self):
        from wilderness_agent import WildernessAgent

        agent = WildernessAgent()
        assert agent.stt_node.__func__ is BaseGameAgent.stt_node


class TestWildernessAgentTools:
    def test_has_exploration_tools(self):
        from wilderness_agent import WILDERNESS_TOOLS

        assert enter_location in WILDERNESS_TOOLS
        assert query_location in WILDERNESS_TOOLS
        assert move_player in WILDERNESS_TOOLS
        assert discover_hidden_element in WILDERNESS_TOOLS

    def test_has_combat_entry(self):
        from wilderness_agent import WILDERNESS_TOOLS

        assert start_combat in WILDERNESS_TOOLS

    def test_has_utility_tools(self):
        from wilderness_agent import WILDERNESS_TOOLS

        assert roll_dice in WILDERNESS_TOOLS
        assert query_inventory in WILDERNESS_TOOLS
        assert query_lore in WILDERNESS_TOOLS
        assert record_story_moment in WILDERNESS_TOOLS
        assert request_skill_check in WILDERNESS_TOOLS
        assert update_quest in WILDERNESS_TOOLS

    def test_no_combat_only_tools(self):
        from wilderness_agent import WILDERNESS_TOOLS

        assert resolve_enemy_turn not in WILDERNESS_TOOLS
        assert end_combat not in WILDERNESS_TOOLS

    def test_tools_match_agent_instance(self):
        from wilderness_agent import WILDERNESS_TOOLS, WildernessAgent

        agent = WildernessAgent()
        assert agent.tools == WILDERNESS_TOOLS


class TestWildernessAgentPrompt:
    def test_prompt_includes_voice_style(self):
        from wilderness_agent import WildernessAgent

        agent = WildernessAgent()
        assert VOICE_STYLE_PROMPT in agent.instructions

    def test_prompt_includes_wilderness(self):
        from wilderness_agent import WildernessAgent

        agent = WildernessAgent()
        assert WILDERNESS_PROMPT in agent.instructions

    def test_prompt_excludes_combat(self):
        from wilderness_agent import WildernessAgent

        agent = WildernessAgent()
        assert COMBAT_PROMPT not in agent.instructions

    def test_prompt_includes_location_context(self):
        from wilderness_agent import WildernessAgent

        agent = WildernessAgent(initial_location="greyvale_south_road")
        assert "greyvale_south_road" in agent.instructions
