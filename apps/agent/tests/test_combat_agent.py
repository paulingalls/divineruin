"""Tests for CombatAgent — combat-specific agent with focused tools and prompt."""

from base_agent import BaseGameAgent
from combat_agent import COMBAT_AGENT_TOOLS, COMBAT_SYSTEM_PROMPT, CombatAgent


class TestCombatAgentConfig:
    """Test CombatAgent is correctly configured."""

    def test_is_subclass_of_base_game_agent(self):
        assert issubclass(CombatAgent, BaseGameAgent)

    def test_combat_tools_are_complete(self):
        from ability_tools import request_ability_activation
        from check_tools import request_attack, request_saving_throw, roll_dice
        from combat_end import end_combat
        from combat_turn import request_death_save, resolve_enemy_turn
        from environment_tools import play_sound, set_music_state
        from query_tools import query_info

        expected = {
            resolve_enemy_turn,
            request_attack,
            request_saving_throw,
            request_death_save,
            end_combat,
            roll_dice,
            play_sound,
            set_music_state,
            query_info,
            request_ability_activation,
        }
        assert set(COMBAT_AGENT_TOOLS) == expected

    def test_combat_tools_exclude_exploration(self):
        from combat_init import start_combat
        from movement_tools import move_player
        from quest_tools import update_quest
        from scene_tools import enter_location

        for tool in [enter_location, move_player, start_combat, update_quest]:
            assert tool not in COMBAT_AGENT_TOOLS

    def test_combat_excludes_milestone_resolution(self):
        # Combat never awards XP (end_combat hands back; the exploration agent calls
        # award_xp), so milestones never resolve here. resolve_milestone lives in the
        # exploration agents instead (concern 3c02318dfa99).
        from milestone_tools import resolve_milestone

        assert resolve_milestone not in COMBAT_AGENT_TOOLS


class TestCombatSystemPrompt:
    """Test COMBAT_SYSTEM_PROMPT content."""

    def test_contains_combat_narration_style(self):
        assert "staccato" in COMBAT_SYSTEM_PROMPT

    def test_contains_initiative_flow(self):
        assert "initiative" in COMBAT_SYSTEM_PROMPT.lower()

    def test_contains_hp_status_guidance(self):
        assert "hp_status" in COMBAT_SYSTEM_PROMPT or "bloodied" in COMBAT_SYSTEM_PROMPT

    def test_contains_voice_style_rules(self):
        assert "spoken aloud" in COMBAT_SYSTEM_PROMPT or "write for the ear" in COMBAT_SYSTEM_PROMPT.lower()

    def test_contains_character_tag_format(self):
        assert "[CHARACTER_NAME" in COMBAT_SYSTEM_PROMPT or "COMPANION_KAEL" in COMBAT_SYSTEM_PROMPT

    def test_contains_companion_combat_instructions(self):
        assert "companion" in COMBAT_SYSTEM_PROMPT.lower()
