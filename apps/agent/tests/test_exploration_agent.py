from activate_tools import activate
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
        for region in (REGION_CITY, REGION_WILDERNESS, REGION_DUNGEON):
            agent = ExplorationAgent(region_type=region)
            assert agent._agent_type == region


class TestExplorationToolset:
    def test_count_at_fifteen_under_ceiling(self):
        from llm_config import MAX_STRICT_TOOLS

        assert len(EXPLORATION_TOOLS) == 15
        assert len(EXPLORATION_TOOLS) <= MAX_STRICT_TOOLS

    def test_holds_unified_superset(self):
        from check_tools import check
        from choice_tools import select
        from inventory_tools import transact
        from mode_tools import enter_mode
        from reputation_tools import adjust_faction_reputation
        from session_tools import update_npc_disposition

        for tool in (
            check,
            select,
            transact,
            enter_mode,
            update_npc_disposition,
            adjust_faction_reputation,
        ):
            assert tool in EXPLORATION_TOOLS

    def test_activate_registered_deploy_veil_anchor_wrapper_gone(self):
        assert activate in EXPLORATION_TOOLS
        assert "deploy_veil_anchor" not in {t.__name__ for t in EXPLORATION_TOOLS}


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
