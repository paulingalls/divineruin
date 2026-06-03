"""Tests for WildernessAgent — wilderness/travel gameplay agent."""

from base_agent import BaseGameAgent
from check_tools import discover_hidden_element, request_skill_check, roll_dice
from combat_end import end_combat
from combat_init import start_combat
from combat_turn import resolve_enemy_turn
from movement_tools import move_player
from query_tools import query_info
from quest_tools import update_quest
from scene_tools import enter_location
from session_tools import record_story_moment
from system_prompts import COMBAT_PROMPT, VOICE_STYLE_PROMPT, WILDERNESS_PROMPT, build_system_prompt
from wilderness_agent import WILDERNESS_TOOLS, WildernessAgent


class TestWildernessAgentConfig:
    def test_inherits_base_game_agent(self):
        assert issubclass(WildernessAgent, BaseGameAgent)

    def test_agent_type_is_wilderness(self):
        assert WildernessAgent._agent_type == "wilderness"


class TestWildernessAgentTools:
    def test_has_exploration_tools(self):
        assert enter_location in WILDERNESS_TOOLS
        assert query_info in WILDERNESS_TOOLS
        assert move_player in WILDERNESS_TOOLS
        assert discover_hidden_element in WILDERNESS_TOOLS

    def test_has_combat_entry(self):
        assert start_combat in WILDERNESS_TOOLS

    def test_has_utility_tools(self):
        assert roll_dice in WILDERNESS_TOOLS
        assert record_story_moment in WILDERNESS_TOOLS
        assert request_skill_check in WILDERNESS_TOOLS
        assert update_quest in WILDERNESS_TOOLS

    def test_no_combat_only_tools(self):
        assert resolve_enemy_turn not in WILDERNESS_TOOLS
        assert end_combat not in WILDERNESS_TOOLS

    def test_has_milestone_resolution(self):
        # Leveling happens here via award_xp, so the select verb must be reachable by the
        # DM to resolve the L5 specialization fork (concern 3c02318dfa99).
        from choice_tools import select

        assert select in WILDERNESS_TOOLS


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
