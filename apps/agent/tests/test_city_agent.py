"""Tests for CityAgent — settlement/city gameplay agent."""

from base_agent import BaseGameAgent
from city_agent import CITY_TOOLS, CityAgent
from gameplay_agent import GameplayAgent
from region_types import REGION_CITY


class TestCityAgentConfig:
    def test_inherits_gameplay_agent(self):
        assert issubclass(CityAgent, GameplayAgent)
        assert issubclass(CityAgent, BaseGameAgent)

    def test_agent_type_is_city(self):
        assert CityAgent._agent_type == REGION_CITY


class TestCityAgentTools:
    def test_has_xp_award(self):
        from progression_tools import award_xp

        assert award_xp in CITY_TOOLS

    def test_has_milestone_resolution(self):
        # Leveling (and thus the L5 specialization fork) happens here via award_xp, so
        # resolve_milestone must be reachable by the DM in this agent (concern 3c02318dfa99).
        from milestone_tools import resolve_milestone

        assert resolve_milestone in CITY_TOOLS
