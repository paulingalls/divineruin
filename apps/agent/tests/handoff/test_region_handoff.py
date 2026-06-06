"""Tests for move_player region moves (M7 story-003): region crossings keep ONE
warm ExplorationAgent (no handoff); only the dispatch/training handoff persists.

Region rides the Stage now (story-002): the system prompt is region-agnostic and
the warm layer reads region from the location. So crossing a region boundary no
longer swaps agents — the same instance persists and its _agent_type is updated
in place via gameplay_agent.set_agent_region.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sample_fixtures import mock_txn

from exploration_agent import ExplorationAgent
from session_data import CompanionState, SessionData


def _move_mocks(location_map: dict) -> dict:
    """Standard mocks for _move_player_impl, keyed off a {loc_id: loc_dict} map."""
    mock_db = MagicMock()
    mock_db.transaction = lambda: mock_txn(MagicMock())
    mock_db.extract_exit_connections = MagicMock(return_value=[])
    mock_mutations = MagicMock()
    mock_mutations.update_player_location = AsyncMock()
    mock_mutations.upsert_map_progress = AsyncMock()
    mock_queries = MagicMock()
    mock_queries.get_player = AsyncMock(return_value={"name": "Test", "level": 1})
    mock_queries.get_targets_at_location = AsyncMock(return_value=[])
    mock_queries.get_npc_dispositions = AsyncMock(return_value={})
    mock_queries.get_npcs_at_location = AsyncMock(return_value=[])
    mock_content = MagicMock()
    mock_content.get_location = AsyncMock(side_effect=lambda loc_id: location_map.get(loc_id))
    return {"db_mod": mock_db, "mutations": mock_mutations, "queries": mock_queries, "content": mock_content}


def _ctx_with_agent(start_location: str, agent, companion=None):
    """A RunContext whose live current_agent is `agent` (so handoff/identity is observable)."""
    ctx = MagicMock()
    session = SessionData(player_id="player_1", location_id=start_location)
    if companion is not None:
        session.companion = companion
    ctx.userdata = session
    ctx.session.current_agent = agent
    return ctx


class TestMovePlayerRegionMoveNoHandoff:
    """A region boundary crossing keeps the same agent — returns a plain str."""

    @pytest.mark.asyncio
    async def test_city_to_wilderness_returns_string_same_agent(self):
        from movement_tools import _move_player_impl

        locs = {
            "accord_market_square": {
                "id": "accord_market_square",
                "name": "Market Square",
                "region_type": "city",
                "exits": {"south": {"destination": "greyvale_south_road"}},
            },
            "greyvale_south_road": {
                "id": "greyvale_south_road",
                "name": "South Road",
                "region_type": "wilderness",
                "description": "A dusty road heading south.",
                "atmosphere": "open, windswept",
                "exits": {"north": {"destination": "accord_market_square"}},
            },
        }
        agent = ExplorationAgent(initial_location="accord_market_square", region_type="city")
        ctx = _ctx_with_agent("accord_market_square", agent)

        with patch("movement_tools.publish_game_event", new_callable=AsyncMock):
            result = await _move_player_impl(ctx, "greyvale_south_road", **_move_mocks(locs))

        assert isinstance(result, str), f"region move must not hand off; got {type(result)}"
        # Same agent instance persists (no handoff)...
        assert ctx.session.current_agent is agent
        # ...with its region updated in place to match the new Stage.
        assert agent._agent_type == "wilderness"

    @pytest.mark.asyncio
    async def test_wilderness_to_dungeon_updates_region_in_place(self):
        from movement_tools import _move_player_impl

        locs = {
            "greyvale_wilderness_north": {
                "id": "greyvale_wilderness_north",
                "name": "Northern Wilderness",
                "region_type": "wilderness",
                "exits": {"east": {"destination": "greyvale_ruins_entrance"}},
            },
            "greyvale_ruins_entrance": {
                "id": "greyvale_ruins_entrance",
                "name": "Ruins Entrance",
                "region_type": "dungeon",
                "description": "Cold stone steps descend into darkness.",
                "atmosphere": "oppressive, damp",
                "exits": {"west": {"destination": "greyvale_wilderness_north"}},
            },
        }
        agent = ExplorationAgent(initial_location="greyvale_wilderness_north", region_type="wilderness")
        ctx = _ctx_with_agent("greyvale_wilderness_north", agent)

        with patch("movement_tools.publish_game_event", new_callable=AsyncMock):
            result = await _move_player_impl(ctx, "greyvale_ruins_entrance", **_move_mocks(locs))

        assert isinstance(result, str)
        assert ctx.session.current_agent is agent
        assert agent._agent_type == "dungeon"

    @pytest.mark.asyncio
    async def test_same_region_returns_string(self):
        from movement_tools import _move_player_impl

        locs = {
            "accord_market_square": {
                "id": "accord_market_square",
                "name": "Market Square",
                "region_type": "city",
                "exits": {"north": {"destination": "accord_guild_hall"}},
            },
            "accord_guild_hall": {
                "id": "accord_guild_hall",
                "name": "Guild Hall",
                "region_type": "city",
                "description": "Heavy oak doors.",
                "atmosphere": "busy",
                "exits": {"south": {"destination": "accord_market_square"}},
            },
        }
        agent = ExplorationAgent(initial_location="accord_market_square", region_type="city")
        ctx = _ctx_with_agent("accord_market_square", agent)

        with patch("movement_tools.publish_game_event", new_callable=AsyncMock):
            result = await _move_player_impl(ctx, "accord_guild_hall", **_move_mocks(locs))

        assert isinstance(result, str)
        assert ctx.session.current_agent is agent
        assert agent._agent_type == "city"

    @pytest.mark.asyncio
    async def test_region_move_with_companion_keeps_one_agent(self):
        """Companion persists trivially — there's no handoff, so the same agent (and
        its session companion) carry across the region boundary."""
        from movement_tools import _move_player_impl

        locs = {
            "accord_market_square": {
                "id": "accord_market_square",
                "name": "Market Square",
                "region_type": "city",
                "exits": {"south": {"destination": "greyvale_south_road"}},
            },
            "greyvale_south_road": {
                "id": "greyvale_south_road",
                "name": "Greyvale South Road",
                "region_type": "wilderness",
                "description": "A dusty road.",
                "atmosphere": "windswept",
                "exits": {},
            },
        }
        agent = ExplorationAgent(initial_location="accord_market_square", region_type="city")
        companion = CompanionState(id="companion_kael", name="Kael")
        ctx = _ctx_with_agent("accord_market_square", agent, companion=companion)

        with patch("movement_tools.publish_game_event", new_callable=AsyncMock):
            result = await _move_player_impl(ctx, "greyvale_south_road", **_move_mocks(locs))

        assert isinstance(result, str)
        assert ctx.session.current_agent is agent
        assert ctx.userdata.companion is companion


class TestMovePlayerDispatchHandoffPreserved:
    """The dispatch/training handoff is an ACTIVITY change, not a region change —
    it MUST still return a (DispatchAgent, str) tuple."""

    @pytest.mark.asyncio
    async def test_move_into_training_returns_dispatch_handoff(self):
        from dispatch_agent import DispatchAgent
        from movement_tools import _move_player_impl

        locs = {
            "accord_market_square": {
                "id": "accord_market_square",
                "name": "Market Square",
                "region_type": "city",
                "exits": {"north": {"destination": "accord_training_hall"}},
            },
            "accord_training_hall": {
                "id": "accord_training_hall",
                "name": "Training Hall",
                "region_type": "city",
                "agent_context": "training",
                "description": "Mats and practice dummies.",
                "atmosphere": "focused",
                "exits": {"south": {"destination": "accord_market_square"}},
            },
        }
        agent = ExplorationAgent(initial_location="accord_market_square", region_type="city")
        ctx = _ctx_with_agent("accord_market_square", agent)

        with patch("movement_tools.publish_game_event", new_callable=AsyncMock):
            result = await _move_player_impl(ctx, "accord_training_hall", **_move_mocks(locs))

        assert isinstance(result, tuple), "entering training must hand off to the dispatch agent"
        handoff_agent, json_str = result
        assert isinstance(handoff_agent, DispatchAgent)
        assert isinstance(json_str, str)


class TestSetAgentRegion:
    """The shared primitive used by movement_tools + quest_tools to keep a
    persisting agent's region honest without a handoff."""

    def test_updates_exploration_agent_region(self):
        from gameplay_agent import set_agent_region

        agent = ExplorationAgent(initial_location="accord_guild_hall", region_type="city")
        set_agent_region(agent, "dungeon")
        assert agent._agent_type == "dungeon"

    def test_unknown_region_defaults_to_city(self):
        from gameplay_agent import set_agent_region

        agent = ExplorationAgent(initial_location="accord_guild_hall", region_type="wilderness")
        set_agent_region(agent, "bogus")
        assert agent._agent_type == "city"

    def test_noop_for_non_region_agent(self):
        from gameplay_agent import set_agent_region

        # A plain object without _agent_type must be left untouched (no crash).
        sentinel = object()
        set_agent_region(sentinel, "dungeon")
        assert not hasattr(sentinel, "_agent_type")
