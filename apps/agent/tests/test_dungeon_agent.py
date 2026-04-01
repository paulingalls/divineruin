"""Tests for DungeonAgent — dungeon exploration gameplay agent."""

from base_agent import BaseGameAgent
from dungeon_agent import DUNGEON_TOOLS, DungeonAgent
from prompts import COMBAT_PROMPT, DUNGEON_PROMPT, VOICE_STYLE_PROMPT, build_system_prompt
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


class TestDungeonAgentConfig:
    def test_inherits_base_game_agent(self):
        assert issubclass(DungeonAgent, BaseGameAgent)

    def test_agent_type_is_dungeon(self):
        assert DungeonAgent._agent_type == "dungeon"


class TestDungeonAgentTools:
    def test_has_exploration_tools(self):
        assert enter_location in DUNGEON_TOOLS
        assert query_location in DUNGEON_TOOLS
        assert move_player in DUNGEON_TOOLS
        assert discover_hidden_element in DUNGEON_TOOLS
        assert request_skill_check in DUNGEON_TOOLS
        assert request_saving_throw in DUNGEON_TOOLS

    def test_has_combat_entry(self):
        assert start_combat in DUNGEON_TOOLS

    def test_has_inventory_tools(self):
        assert query_inventory in DUNGEON_TOOLS
        assert add_to_inventory in DUNGEON_TOOLS

    def test_has_utility_tools(self):
        assert roll_dice in DUNGEON_TOOLS
        assert query_lore in DUNGEON_TOOLS
        assert record_story_moment in DUNGEON_TOOLS
        assert update_quest in DUNGEON_TOOLS

    def test_no_combat_only_tools(self):
        assert resolve_enemy_turn not in DUNGEON_TOOLS
        assert end_combat not in DUNGEON_TOOLS


class TestDungeonAgentPrompt:
    def test_prompt_includes_voice_style(self):
        prompt = build_system_prompt("greyvale_ruins_entrance", region_type="dungeon")
        assert VOICE_STYLE_PROMPT in prompt

    def test_prompt_includes_dungeon(self):
        prompt = build_system_prompt("greyvale_ruins_entrance", region_type="dungeon")
        assert DUNGEON_PROMPT in prompt

    def test_prompt_excludes_combat(self):
        prompt = build_system_prompt("greyvale_ruins_entrance", region_type="dungeon")
        assert COMBAT_PROMPT not in prompt

    def test_prompt_includes_location_context(self):
        prompt = build_system_prompt("greyvale_ruins_entrance", region_type="dungeon")
        assert "greyvale_ruins_entrance" in prompt
