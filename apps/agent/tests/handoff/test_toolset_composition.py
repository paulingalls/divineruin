"""Tests that the gameplay/combat agents expose the correct tool sets (completeness + isolation)."""

from check_tools import request_attack
from combat_agent import COMBAT_AGENT_TOOLS
from combat_end import end_combat
from combat_turn import request_death_save, resolve_enemy_turn
from exploration_agent import EXPLORATION_TOOLS
from mode_tools import enter_mode
from movement_tools import move_player
from progression_tools import award_xp
from query_tools import query_info
from quest_tools import update_quest
from scene_tools import enter_location
from session_tools import end_session


class TestToolSetCompleteness:
    """The single exploration agent serves every region, so one tool list carries
    award_xp and end_session for city/wilderness/dungeon alike."""

    def test_exploration_has_award_xp(self):
        assert award_xp in EXPLORATION_TOOLS

    def test_exploration_has_end_session(self):
        assert end_session in EXPLORATION_TOOLS


class TestToolIsolation:
    """Verify the exploration agent and CombatAgent have the correct tool sets."""

    def test_exploration_has_enter_mode(self):
        """Exploration holds the enter_mode handoff verb (folds combat/dispatch/blacksmith)."""
        assert enter_mode in EXPLORATION_TOOLS

    def test_exploration_does_not_have_combat_only_tools(self):
        assert resolve_enemy_turn not in EXPLORATION_TOOLS
        assert request_death_save not in EXPLORATION_TOOLS
        assert end_combat not in EXPLORATION_TOOLS

    def test_exploration_does_not_have_danger_mechanics(self):
        """Exploration escalates violence via enter_mode(mode="combat") — request_attack
        stays a combat-only tool, never in the exploration baseline. (Hazard saves are now
        a mode of the universal `check` verb, M5 story-003, so they're no longer a separate
        tool to exclude.)"""
        assert request_attack not in EXPLORATION_TOOLS

    def test_exploration_has_exploration_tools(self):
        assert enter_location in EXPLORATION_TOOLS
        assert move_player in EXPLORATION_TOOLS
        assert query_info in EXPLORATION_TOOLS
        assert update_quest in EXPLORATION_TOOLS

    def test_combat_agent_has_combat_tools(self):
        """CombatAgent should have combat-specific tools."""
        assert resolve_enemy_turn in COMBAT_AGENT_TOOLS
        assert request_death_save in COMBAT_AGENT_TOOLS
        assert end_combat in COMBAT_AGENT_TOOLS

    def test_combat_agent_does_not_have_exploration_tools(self):
        """CombatAgent should NOT have exploration tools."""
        assert enter_location not in COMBAT_AGENT_TOOLS
        assert move_player not in COMBAT_AGENT_TOOLS
        assert enter_mode not in COMBAT_AGENT_TOOLS
        assert update_quest not in COMBAT_AGENT_TOOLS
