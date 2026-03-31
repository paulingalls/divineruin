"""Tests for DungeonAgent — dungeon exploration gameplay agent."""

from base_agent import BaseGameAgent
from prompts import COMBAT_PROMPT, DUNGEON_PROMPT, VOICE_STYLE_PROMPT
from tools import (
    add_to_inventory,
    discover_hidden_element,
    end_combat,
    enter_location,
    move_player,
    query_inventory,
    query_location,
    query_lore,
    record_story_moment,
    request_saving_throw,
    request_skill_check,
    resolve_enemy_turn,
    roll_dice,
    start_combat,
    update_quest,
)


class TestDungeonAgentInheritance:
    def test_inherits_base_game_agent(self):
        from dungeon_agent import DungeonAgent

        agent = DungeonAgent()
        assert isinstance(agent, BaseGameAgent)

    def test_agent_type_is_dungeon(self):
        from dungeon_agent import DungeonAgent

        agent = DungeonAgent()
        assert agent._agent_type == "dungeon"

    def test_has_tts_node(self):
        from dungeon_agent import DungeonAgent

        agent = DungeonAgent()
        assert agent.tts_node.__func__ is BaseGameAgent.tts_node


class TestDungeonAgentTools:
    def test_has_exploration_tools(self):
        from dungeon_agent import DUNGEON_TOOLS

        assert enter_location in DUNGEON_TOOLS
        assert query_location in DUNGEON_TOOLS
        assert move_player in DUNGEON_TOOLS
        assert discover_hidden_element in DUNGEON_TOOLS
        assert request_skill_check in DUNGEON_TOOLS
        assert request_saving_throw in DUNGEON_TOOLS

    def test_has_combat_entry(self):
        from dungeon_agent import DUNGEON_TOOLS

        assert start_combat in DUNGEON_TOOLS

    def test_has_inventory_tools(self):
        from dungeon_agent import DUNGEON_TOOLS

        assert query_inventory in DUNGEON_TOOLS
        assert add_to_inventory in DUNGEON_TOOLS

    def test_has_utility_tools(self):
        from dungeon_agent import DUNGEON_TOOLS

        assert roll_dice in DUNGEON_TOOLS
        assert query_lore in DUNGEON_TOOLS
        assert record_story_moment in DUNGEON_TOOLS
        assert update_quest in DUNGEON_TOOLS

    def test_no_combat_only_tools(self):
        from dungeon_agent import DUNGEON_TOOLS

        assert resolve_enemy_turn not in DUNGEON_TOOLS
        assert end_combat not in DUNGEON_TOOLS

    def test_tools_match_agent_instance(self):
        from dungeon_agent import DUNGEON_TOOLS, DungeonAgent

        agent = DungeonAgent()
        assert agent.tools == DUNGEON_TOOLS


class TestDungeonAgentPrompt:
    def test_prompt_includes_voice_style(self):
        from dungeon_agent import DungeonAgent

        agent = DungeonAgent()
        assert VOICE_STYLE_PROMPT in agent.instructions

    def test_prompt_includes_dungeon(self):
        from dungeon_agent import DungeonAgent

        agent = DungeonAgent()
        assert DUNGEON_PROMPT in agent.instructions

    def test_prompt_excludes_combat(self):
        from dungeon_agent import DungeonAgent

        agent = DungeonAgent()
        assert COMBAT_PROMPT not in agent.instructions

    def test_prompt_includes_location_context(self):
        from dungeon_agent import DungeonAgent

        agent = DungeonAgent(initial_location="greyvale_ruins_entrance")
        assert "greyvale_ruins_entrance" in agent.instructions
