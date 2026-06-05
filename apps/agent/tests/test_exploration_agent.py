"""Tests for ExplorationAgent — the unified region-agnostic gameplay agent.

M7 collapses CityAgent/WildernessAgent/DungeonAgent into one ExplorationAgent
that carries region_type as a per-instance attribute. The unified tool list is
the former city superset (city ⊇ wilderness, city ⊇ dungeon), so one list of 15
serves every region with headroom under the strict-tool ceiling.
"""

from base_agent import BaseGameAgent
from exploration_agent import EXPLORATION_TOOLS, ExplorationAgent
from gameplay_agent import create_gameplay_agent
from region_types import REGION_CITY, REGION_DUNGEON, REGION_WILDERNESS


class TestExplorationAgentConfig:
    def test_inherits_base_game_agent(self):
        assert issubclass(ExplorationAgent, BaseGameAgent)

    def test_default_region_is_city(self):
        agent = ExplorationAgent()
        assert agent._agent_type == REGION_CITY

    def test_region_type_set_per_instance(self):
        # combat_init.py reads getattr(agent, "_agent_type") to remember the
        # pre-combat region; the attribute must reflect the instance's region.
        for region in (REGION_CITY, REGION_WILDERNESS, REGION_DUNGEON):
            agent = ExplorationAgent(region_type=region)
            assert agent._agent_type == region


class TestExplorationToolset:
    def test_count_at_fifteen_under_ceiling(self):
        from llm_config import MAX_STRICT_TOOLS

        # The unified list is the former CITY_TOOLS (15). With one agent there are
        # 5 free slots — the per-region ceiling no longer binds (debt e665104c753a).
        assert len(EXPLORATION_TOOLS) == 15
        assert len(EXPLORATION_TOOLS) <= MAX_STRICT_TOOLS

    def test_holds_unified_superset(self):
        from check_tools import check
        from choice_tools import select
        from inventory_tools import transact
        from mode_tools import enter_mode
        from progression_tools import award_divine_favor, award_xp
        from session_tools import update_npc_disposition

        for tool in (check, select, transact, enter_mode, award_xp, award_divine_favor, update_npc_disposition):
            assert tool in EXPLORATION_TOOLS

    def test_excludes_combat_only_tools(self):
        from check_tools import request_attack

        assert request_attack not in EXPLORATION_TOOLS


class TestExplorationFactory:
    def test_factory_returns_exploration_agent_per_region(self):
        for region in (REGION_CITY, REGION_WILDERNESS, REGION_DUNGEON):
            agent = create_gameplay_agent(region, "some_location")
            assert isinstance(agent, ExplorationAgent)
            assert agent._agent_type == region

    def test_unknown_region_defaults_to_city(self):
        agent = create_gameplay_agent("unknown", "somewhere")
        assert isinstance(agent, ExplorationAgent)
        assert agent._agent_type == REGION_CITY
