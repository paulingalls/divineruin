"""Tests for WildernessAgent — wilderness/travel gameplay agent."""

from base_agent import BaseGameAgent
from system_prompts import COMBAT_PROMPT, VOICE_STYLE_PROMPT, WILDERNESS_PROMPT, build_system_prompt
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
from wilderness_agent import WILDERNESS_TOOLS, WildernessAgent


class TestWildernessAgentConfig:
    def test_inherits_base_game_agent(self):
        assert issubclass(WildernessAgent, BaseGameAgent)

    def test_agent_type_is_wilderness(self):
        assert WildernessAgent._agent_type == "wilderness"


class TestWildernessAgentTools:
    def test_has_exploration_tools(self):
        assert enter_location in WILDERNESS_TOOLS
        assert query_location in WILDERNESS_TOOLS
        assert move_player in WILDERNESS_TOOLS
        assert discover_hidden_element in WILDERNESS_TOOLS

    def test_has_combat_entry(self):
        assert start_combat in WILDERNESS_TOOLS

    def test_has_utility_tools(self):
        assert roll_dice in WILDERNESS_TOOLS
        assert query_inventory in WILDERNESS_TOOLS
        assert query_lore in WILDERNESS_TOOLS
        assert record_story_moment in WILDERNESS_TOOLS
        assert request_skill_check in WILDERNESS_TOOLS
        assert update_quest in WILDERNESS_TOOLS

    def test_no_combat_only_tools(self):
        assert resolve_enemy_turn not in WILDERNESS_TOOLS
        assert end_combat not in WILDERNESS_TOOLS


class TestWildernessAgentPrompt:
    def test_prompt_includes_voice_style(self):
        prompt = build_system_prompt("greyvale_south_road", region_type="wilderness")
        assert VOICE_STYLE_PROMPT in prompt

    def test_prompt_includes_wilderness(self):
        prompt = build_system_prompt("greyvale_south_road", region_type="wilderness")
        assert WILDERNESS_PROMPT in prompt

    def test_prompt_excludes_combat(self):
        prompt = build_system_prompt("greyvale_south_road", region_type="wilderness")
        assert COMBAT_PROMPT not in prompt

    def test_prompt_includes_location_context(self):
        prompt = build_system_prompt("greyvale_south_road", region_type="wilderness")
        assert "greyvale_south_road" in prompt
