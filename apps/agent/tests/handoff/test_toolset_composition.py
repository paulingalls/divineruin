"""Tests that each gameplay agent exposes the correct tool set (completeness + isolation)."""

from check_tools import request_attack
from city_agent import CITY_TOOLS
from combat_agent import COMBAT_AGENT_TOOLS
from combat_end import end_combat
from combat_init import start_combat
from combat_turn import request_death_save, resolve_enemy_turn
from dungeon_agent import DUNGEON_TOOLS
from movement_tools import move_player
from progression_tools import award_xp
from query_tools import query_info
from quest_tools import update_quest
from scene_tools import enter_location
from session_tools import end_session
from wilderness_agent import WILDERNESS_TOOLS


class TestToolSetCompleteness:
    """Verify that all gameplay agents have award_xp and end_session."""

    def test_wilderness_has_award_xp(self):
        assert award_xp in WILDERNESS_TOOLS

    def test_wilderness_has_end_session(self):
        assert end_session in WILDERNESS_TOOLS

    def test_dungeon_has_award_xp(self):
        assert award_xp in DUNGEON_TOOLS

    def test_dungeon_has_end_session(self):
        assert end_session in DUNGEON_TOOLS

    def test_city_has_award_xp(self):
        """Baseline -- CityAgent already has these."""
        assert award_xp in CITY_TOOLS

    def test_city_has_end_session(self):
        assert end_session in CITY_TOOLS


class TestToolIsolation:
    """Verify that CityAgent and CombatAgent have the correct tool sets."""

    def test_city_has_start_combat(self):
        """CityAgent should have start_combat tool."""
        assert start_combat in CITY_TOOLS

    def test_city_does_not_have_combat_only_tools(self):
        """CityAgent should NOT have combat-only tools."""
        assert resolve_enemy_turn not in CITY_TOOLS
        assert request_death_save not in CITY_TOOLS
        assert end_combat not in CITY_TOOLS

    def test_city_does_not_have_danger_mechanics(self):
        """A peaceful settlement escalates violence via start_combat — request_attack
        stays a combat-only tool, never in the city baseline. (Hazard saves are now a
        mode of the universal `check` verb, M5 story-003, so they're no longer a
        separate tool to exclude.)"""
        assert request_attack not in CITY_TOOLS

    def test_city_has_exploration_tools(self):
        """CityAgent should have exploration and mutation tools."""
        assert enter_location in CITY_TOOLS
        assert move_player in CITY_TOOLS
        assert query_info in CITY_TOOLS
        assert update_quest in CITY_TOOLS

    def test_combat_agent_has_combat_tools(self):
        """CombatAgent should have combat-specific tools."""
        assert resolve_enemy_turn in COMBAT_AGENT_TOOLS
        assert request_death_save in COMBAT_AGENT_TOOLS
        assert end_combat in COMBAT_AGENT_TOOLS

    def test_combat_agent_does_not_have_exploration_tools(self):
        """CombatAgent should NOT have exploration tools."""
        assert enter_location not in COMBAT_AGENT_TOOLS
        assert move_player not in COMBAT_AGENT_TOOLS
        assert start_combat not in COMBAT_AGENT_TOOLS
        assert update_quest not in COMBAT_AGENT_TOOLS
