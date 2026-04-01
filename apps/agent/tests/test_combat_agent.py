"""Tests for CombatAgent — combat-specific agent with focused tools and prompt."""

from base_agent import BaseGameAgent
from combat_agent import COMBAT_AGENT_TOOLS, COMBAT_SYSTEM_PROMPT, CombatAgent


class TestCombatAgentConfig:
    """Test CombatAgent is correctly configured."""

    def test_is_subclass_of_base_game_agent(self):
        assert issubclass(CombatAgent, BaseGameAgent)

    def test_combat_tools_are_complete(self):
        from tools import (
            end_combat,
            play_sound,
            query_inventory,
            request_attack,
            request_death_save,
            request_saving_throw,
            resolve_enemy_turn,
            roll_dice,
            set_music_state,
        )

        expected = {
            resolve_enemy_turn,
            request_attack,
            request_saving_throw,
            request_death_save,
            end_combat,
            roll_dice,
            play_sound,
            set_music_state,
            query_inventory,
        }
        assert set(COMBAT_AGENT_TOOLS) == expected

    def test_combat_tools_exclude_exploration(self):
        from tools import (
            enter_location,
            move_player,
            query_location,
            query_npc,
            start_combat,
            update_quest,
        )

        for tool in [enter_location, move_player, query_location, query_npc, start_combat, update_quest]:
            assert tool not in COMBAT_AGENT_TOOLS


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
