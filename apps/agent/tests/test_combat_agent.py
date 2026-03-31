"""Tests for CombatAgent — combat-specific agent with focused tools and prompt."""

from combat_agent import COMBAT_AGENT_TOOLS, COMBAT_SYSTEM_PROMPT, CombatAgent


class TestCombatAgentInit:
    """Test CombatAgent initialization."""

    def test_init_uses_combat_system_prompt(self):
        """CombatAgent should use COMBAT_SYSTEM_PROMPT as instructions."""
        agent = CombatAgent()
        assert agent.instructions == COMBAT_SYSTEM_PROMPT

    def test_init_uses_combat_tools(self):
        """CombatAgent should have exactly the combat tool set."""
        agent = CombatAgent()
        assert agent.tools == COMBAT_AGENT_TOOLS

    def test_init_accepts_chat_ctx(self):
        """CombatAgent should accept and pass chat_ctx."""
        from livekit.agents.llm import ChatContext

        ctx = ChatContext()
        ctx.add_message(role="user", content="combat context")
        agent = CombatAgent(chat_ctx=ctx)
        assert len(agent.chat_ctx.items) > 0


class TestCombatAgentToolList:
    """Test that CombatAgent has exactly the right tools."""

    def test_has_resolve_enemy_turn(self):
        """CombatAgent should have resolve_enemy_turn tool."""
        from tools import resolve_enemy_turn

        assert resolve_enemy_turn in COMBAT_AGENT_TOOLS

    def test_has_request_attack(self):
        """CombatAgent should have request_attack tool."""
        from tools import request_attack

        assert request_attack in COMBAT_AGENT_TOOLS

    def test_has_request_saving_throw(self):
        """CombatAgent should have request_saving_throw tool."""
        from tools import request_saving_throw

        assert request_saving_throw in COMBAT_AGENT_TOOLS

    def test_has_request_death_save(self):
        """CombatAgent should have request_death_save tool."""
        from tools import request_death_save

        assert request_death_save in COMBAT_AGENT_TOOLS

    def test_has_end_combat(self):
        """CombatAgent should have end_combat tool."""
        from tools import end_combat

        assert end_combat in COMBAT_AGENT_TOOLS

    def test_has_roll_dice(self):
        """CombatAgent should have roll_dice tool."""
        from tools import roll_dice

        assert roll_dice in COMBAT_AGENT_TOOLS

    def test_has_play_sound(self):
        """CombatAgent should have play_sound tool."""
        from tools import play_sound

        assert play_sound in COMBAT_AGENT_TOOLS

    def test_has_set_music_state(self):
        """CombatAgent should have set_music_state tool."""
        from tools import set_music_state

        assert set_music_state in COMBAT_AGENT_TOOLS

    def test_has_query_inventory(self):
        """CombatAgent should have query_inventory tool."""
        from tools import query_inventory

        assert query_inventory in COMBAT_AGENT_TOOLS

    def test_does_not_have_exploration_tools(self):
        """CombatAgent should NOT have exploration/mutation tools."""
        from tools import (
            enter_location,
            move_player,
            query_location,
            query_npc,
            start_combat,
            update_quest,
        )

        for tool in [enter_location, move_player, query_location, query_npc, start_combat, update_quest]:
            assert tool not in COMBAT_AGENT_TOOLS, f"{tool.__name__} should not be in CombatAgent tools"


class TestCombatSystemPrompt:
    """Test COMBAT_SYSTEM_PROMPT content."""

    def test_contains_combat_narration_style(self):
        """Prompt should include staccato combat narration instructions."""
        assert "staccato" in COMBAT_SYSTEM_PROMPT

    def test_contains_initiative_flow(self):
        """Prompt should describe the combat flow per round."""
        assert "initiative" in COMBAT_SYSTEM_PROMPT.lower()

    def test_contains_hp_status_guidance(self):
        """Prompt should tell the LLM to use hp_status, not reveal exact numbers."""
        assert "hp_status" in COMBAT_SYSTEM_PROMPT or "bloodied" in COMBAT_SYSTEM_PROMPT

    def test_contains_voice_style_rules(self):
        """Prompt should include shared voice-style rules (write for the ear, etc.)."""
        assert "spoken aloud" in COMBAT_SYSTEM_PROMPT or "write for the ear" in COMBAT_SYSTEM_PROMPT.lower()

    def test_contains_character_tag_format(self):
        """Prompt should include the ventriloquism tag format."""
        assert "[CHARACTER_NAME" in COMBAT_SYSTEM_PROMPT or "COMPANION_KAEL" in COMBAT_SYSTEM_PROMPT

    def test_contains_companion_combat_instructions(self):
        """Prompt should include companion combat behavior."""
        assert "companion" in COMBAT_SYSTEM_PROMPT.lower()


class TestCombatAgentInheritance:
    """Test that CombatAgent inherits BaseGameAgent voice pipeline."""

    def test_inherits_from_base_game_agent(self):
        """CombatAgent should be a subclass of BaseGameAgent."""
        from base_agent import BaseGameAgent

        assert issubclass(CombatAgent, BaseGameAgent)

    def test_has_tts_node(self):
        """CombatAgent should inherit tts_node from BaseGameAgent."""
        agent = CombatAgent()
        assert hasattr(agent, "tts_node")
        assert callable(agent.tts_node)

    def test_has_stt_node(self):
        """CombatAgent should inherit stt_node from BaseGameAgent."""
        agent = CombatAgent()
        assert hasattr(agent, "stt_node")
        assert callable(agent.stt_node)

    def test_has_llm_node(self):
        """CombatAgent should inherit llm_node from BaseGameAgent."""
        agent = CombatAgent()
        assert hasattr(agent, "llm_node")
        assert callable(agent.llm_node)

    def test_has_fire_and_forget(self):
        """CombatAgent should inherit _fire_and_forget from BaseGameAgent."""
        agent = CombatAgent()
        assert hasattr(agent, "_fire_and_forget")
        assert callable(agent._fire_and_forget)
