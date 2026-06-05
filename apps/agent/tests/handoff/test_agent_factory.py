"""Tests for create_gameplay_agent — returns one ExplorationAgent, region by region_type."""

from exploration_agent import ExplorationAgent
from session_data import CompanionState


class TestGameplayAgentFactory:
    """create_gameplay_agent builds an ExplorationAgent whose region matches region_type."""

    def test_city_region(self):
        from gameplay_agent import create_gameplay_agent

        agent = create_gameplay_agent("city", "accord_guild_hall")
        assert isinstance(agent, ExplorationAgent)
        assert agent._agent_type == "city"

    def test_wilderness_region(self):
        from gameplay_agent import create_gameplay_agent

        agent = create_gameplay_agent("wilderness", "greyvale_south_road")
        assert isinstance(agent, ExplorationAgent)
        assert agent._agent_type == "wilderness"

    def test_dungeon_region(self):
        from gameplay_agent import create_gameplay_agent

        agent = create_gameplay_agent("dungeon", "greyvale_ruins_entrance")
        assert isinstance(agent, ExplorationAgent)
        assert agent._agent_type == "dungeon"

    def test_unknown_defaults_to_city(self):
        from gameplay_agent import create_gameplay_agent

        agent = create_gameplay_agent("unknown", "somewhere")
        assert isinstance(agent, ExplorationAgent)
        assert agent._agent_type == "city"

    def test_passes_companion(self):
        from gameplay_agent import create_gameplay_agent

        companion = CompanionState(id="companion_kael", name="Kael")
        agent = create_gameplay_agent("city", "accord_guild_hall", companion=companion)
        assert isinstance(agent, ExplorationAgent)
