"""Tests that the gameplay/combat agents expose the correct tool sets (completeness + isolation)."""

from combat_agent import COMBAT_AGENT_TOOLS
from combat_death_save import request_death_save
from combat_end import end_combat
from combat_turn import declare_phase, resolve_phase
from exploration_agent import EXPLORATION_TOOLS
from mode_tools import enter_mode
from movement_tools import move_player
from query_tools import query_info
from quest_tools import update_quest
from scene_tools import enter_location
from session_tools import end_session


class TestToolSetCompleteness:
    """The single exploration agent serves every region, so one tool list carries
    end_session for city/wilderness/dungeon alike."""

    def test_exploration_has_no_award_verbs(self):
        """M28: XP and divine favor are granted by deterministic Resolves on combat exit and
        quest completion, never by LLM judgement — so neither verb is registered anywhere.
        Name-based, so it keeps meaning after the symbols themselves are deleted."""
        names = {t.__name__ for t in EXPLORATION_TOOLS}
        assert "award_xp" not in names
        assert "award_divine_favor" not in names

    def test_exploration_has_end_session(self):
        assert end_session in EXPLORATION_TOOLS


class TestToolIsolation:
    """Verify the exploration agent and CombatAgent have the correct tool sets."""

    def test_exploration_has_enter_mode(self):
        """Exploration holds the enter_mode handoff verb (folds combat/dispatch/blacksmith)."""
        assert enter_mode in EXPLORATION_TOOLS

    def test_exploration_does_not_have_combat_only_tools(self):
        assert declare_phase not in EXPLORATION_TOOLS
        assert resolve_phase not in EXPLORATION_TOOLS
        assert request_death_save not in EXPLORATION_TOOLS
        assert end_combat not in EXPLORATION_TOOLS

    def test_exploration_has_exploration_tools(self):
        assert enter_location in EXPLORATION_TOOLS
        assert move_player in EXPLORATION_TOOLS
        assert query_info in EXPLORATION_TOOLS
        assert update_quest in EXPLORATION_TOOLS

    def test_combat_agent_has_combat_tools(self):
        """CombatAgent should have combat-specific tools."""
        assert declare_phase in COMBAT_AGENT_TOOLS
        assert resolve_phase in COMBAT_AGENT_TOOLS
        assert request_death_save in COMBAT_AGENT_TOOLS
        assert end_combat in COMBAT_AGENT_TOOLS

    def test_combat_agent_does_not_have_exploration_tools(self):
        """CombatAgent should NOT have exploration tools."""
        assert enter_location not in COMBAT_AGENT_TOOLS
        assert move_player not in COMBAT_AGENT_TOOLS
        assert enter_mode not in COMBAT_AGENT_TOOLS
        assert update_quest not in COMBAT_AGENT_TOOLS
