"""Tests for BlacksmithAgent — focused NPC-blacksmith repair agent with one prompt.

Split from story-004 (the customer chose a dedicated agent over folding repair into
DispatchAgent). Mirrors CombatAgent's config-test shape (test_combat_agent.py).
"""

from base_agent import BaseGameAgent
from blacksmith_agent import BLACKSMITH_SYSTEM_PROMPT, BLACKSMITH_TOOLS, BlacksmithAgent


class TestBlacksmithAgentConfig:
    """Test BlacksmithAgent is correctly configured."""

    def test_is_subclass_of_base_game_agent(self):
        assert issubclass(BlacksmithAgent, BaseGameAgent)

    def test_blacksmith_tools_are_complete(self):
        from blacksmith_tools import conclude_blacksmith
        from environment_tools import play_sound, set_music_state
        from query_tools import query_info
        from repair_item import repair_item

        expected = {
            repair_item,
            conclude_blacksmith,
            query_info,
            play_sound,
            set_music_state,
        }
        assert set(BLACKSMITH_TOOLS) == expected

    def test_blacksmith_includes_repair_item(self):
        from repair_item import repair_item

        assert repair_item in BLACKSMITH_TOOLS

    def test_blacksmith_tools_exclude_combat_exploration_and_session(self):
        # The forge is a sub-context: the only exit is conclude_blacksmith (mirrors
        # CombatAgent, which omits move_player/end_session and exits via end_combat).
        from combat_init import start_combat
        from movement_tools import move_player
        from scene_tools import enter_location
        from session_tools import end_session

        for tool in [enter_location, move_player, start_combat, end_session]:
            assert tool not in BLACKSMITH_TOOLS


class TestBlacksmithSystemPrompt:
    """Test BLACKSMITH_SYSTEM_PROMPT content."""

    def test_contains_forge_or_repair_narration(self):
        low = BLACKSMITH_SYSTEM_PROMPT.lower()
        assert "forge" in low or "repair" in low

    def test_contains_voice_style_rules(self):
        low = BLACKSMITH_SYSTEM_PROMPT.lower()
        assert "spoken aloud" in BLACKSMITH_SYSTEM_PROMPT or "write for the ear" in low

    def test_contains_character_tag_format(self):
        assert "[CHARACTER_NAME" in BLACKSMITH_SYSTEM_PROMPT

    def test_instructs_conclude_as_the_exit(self):
        # conclude_blacksmith is the sole way back to region play — the prompt must
        # tell the LLM to call it when the player is done, or the player gets stranded.
        assert "conclude_blacksmith" in BLACKSMITH_SYSTEM_PROMPT
