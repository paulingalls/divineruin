"""Tests for DungeonAgent — dungeon exploration gameplay agent."""

from base_agent import BaseGameAgent
from check_tools import discover_hidden_element, request_saving_throw, request_skill_check, roll_dice
from combat_end import end_combat
from combat_init import start_combat
from combat_turn import resolve_enemy_turn
from dungeon_agent import DUNGEON_TOOLS, DungeonAgent
from inventory_tools import add_to_inventory
from movement_tools import move_player
from query_tools import query_info
from quest_tools import update_quest
from scene_tools import enter_location
from session_tools import record_story_moment
from system_prompts import COMBAT_PROMPT, DUNGEON_PROMPT, VOICE_STYLE_PROMPT, build_system_prompt


class TestDungeonAgentConfig:
    def test_inherits_base_game_agent(self):
        assert issubclass(DungeonAgent, BaseGameAgent)

    def test_agent_type_is_dungeon(self):
        assert DungeonAgent._agent_type == "dungeon"


class TestDungeonAgentTools:
    def test_has_exploration_tools(self):
        assert enter_location in DUNGEON_TOOLS
        assert query_info in DUNGEON_TOOLS
        assert move_player in DUNGEON_TOOLS
        assert discover_hidden_element in DUNGEON_TOOLS
        assert request_skill_check in DUNGEON_TOOLS
        assert request_saving_throw in DUNGEON_TOOLS

    def test_has_combat_entry(self):
        assert start_combat in DUNGEON_TOOLS

    def test_has_inventory_tools(self):
        assert query_info in DUNGEON_TOOLS
        assert add_to_inventory in DUNGEON_TOOLS

    def test_has_utility_tools(self):
        assert roll_dice in DUNGEON_TOOLS
        assert record_story_moment in DUNGEON_TOOLS
        assert update_quest in DUNGEON_TOOLS

    def test_no_combat_only_tools(self):
        assert resolve_enemy_turn not in DUNGEON_TOOLS
        assert end_combat not in DUNGEON_TOOLS

    def test_has_milestone_resolution(self):
        # Leveling happens here via award_xp, so the L5 specialization fork must be
        # resolvable by the DM in this agent (concern 3c02318dfa99).
        from milestone_tools import resolve_milestone

        assert resolve_milestone in DUNGEON_TOOLS


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
