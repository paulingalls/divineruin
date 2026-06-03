"""Tests for create_gameplay_agent — returns the correct agent by region_type."""

from city_agent import CityAgent
from session_data import CompanionState


class TestGameplayAgentFactory:
    """create_gameplay_agent returns the correct agent by region_type."""

    def test_city_returns_city_agent(self):
        from gameplay_agent import create_gameplay_agent

        agent = create_gameplay_agent("city", "accord_guild_hall")
        assert isinstance(agent, CityAgent)

    def test_wilderness_returns_wilderness_agent(self):
        from gameplay_agent import create_gameplay_agent
        from wilderness_agent import WildernessAgent

        agent = create_gameplay_agent("wilderness", "greyvale_south_road")
        assert isinstance(agent, WildernessAgent)

    def test_dungeon_returns_dungeon_agent(self):
        from dungeon_agent import DungeonAgent
        from gameplay_agent import create_gameplay_agent

        agent = create_gameplay_agent("dungeon", "greyvale_ruins_entrance")
        assert isinstance(agent, DungeonAgent)

    def test_unknown_defaults_to_city(self):
        from gameplay_agent import create_gameplay_agent

        agent = create_gameplay_agent("unknown", "somewhere")
        assert isinstance(agent, CityAgent)

    def test_passes_companion(self):
        from gameplay_agent import create_gameplay_agent

        companion = CompanionState(id="companion_kael", name="Kael")
        agent = create_gameplay_agent("city", "accord_guild_hall", companion=companion)
        assert isinstance(agent, CityAgent)
