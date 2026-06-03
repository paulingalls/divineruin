"""Tests for move_player region-boundary handoffs and their narration context."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sample_fixtures import mock_txn

from session_data import CompanionState, SessionData


class TestMovePlayerRegionHandoff:
    """move_player triggers handoff when crossing region boundaries."""

    @pytest.mark.asyncio
    async def test_city_to_wilderness_returns_agent_tuple(self):
        """Moving from city to wilderness location returns (WildernessAgent, str)."""
        from movement_tools import _move_player_impl
        from wilderness_agent import WildernessAgent

        city_location = {
            "id": "accord_market_square",
            "name": "Market Square",
            "region_type": "city",
            "exits": {"south": {"destination": "greyvale_south_road"}},
        }
        wilderness_location = {
            "id": "greyvale_south_road",
            "name": "South Road",
            "region_type": "wilderness",
            "description": "A dusty road heading south.",
            "atmosphere": "open, windswept",
            "exits": {"north": {"destination": "accord_market_square"}},
        }

        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_db.transaction = lambda: mock_txn(mock_conn)
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
        mock_content.get_location = AsyncMock(
            side_effect=lambda loc_id: {
                "accord_market_square": city_location,
                "greyvale_south_road": wilderness_location,
            }.get(loc_id)
        )

        ctx = MagicMock()
        session = SessionData(player_id="player_1", location_id="accord_market_square")
        ctx.userdata = session

        with patch("movement_tools.publish_game_event", new_callable=AsyncMock):
            result = await _move_player_impl(
                ctx,
                "greyvale_south_road",
                db_mod=mock_db,
                mutations=mock_mutations,
                queries=mock_queries,
                content=mock_content,
            )

        assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"
        agent, _json_str = result
        assert isinstance(agent, WildernessAgent)

    @pytest.mark.asyncio
    async def test_same_region_returns_string(self):
        """Moving within the same region type returns str (no handoff)."""
        from movement_tools import _move_player_impl

        loc_a = {
            "id": "accord_market_square",
            "name": "Market Square",
            "region_type": "city",
            "exits": {"north": {"destination": "accord_guild_hall"}},
        }
        loc_b = {
            "id": "accord_guild_hall",
            "name": "Guild Hall",
            "region_type": "city",
            "description": "Heavy oak doors.",
            "atmosphere": "busy",
            "exits": {"south": {"destination": "accord_market_square"}},
        }

        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_db.transaction = lambda: mock_txn(mock_conn)
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
        mock_content.get_location = AsyncMock(
            side_effect=lambda loc_id: {
                "accord_market_square": loc_a,
                "accord_guild_hall": loc_b,
            }.get(loc_id)
        )

        ctx = MagicMock()
        session = SessionData(player_id="player_1", location_id="accord_market_square")
        ctx.userdata = session

        with patch("movement_tools.publish_game_event", new_callable=AsyncMock):
            result = await _move_player_impl(
                ctx,
                "accord_guild_hall",
                db_mod=mock_db,
                mutations=mock_mutations,
                queries=mock_queries,
                content=mock_content,
            )

        assert isinstance(result, str), f"Expected str, got {type(result)}"

    @pytest.mark.asyncio
    async def test_wilderness_to_dungeon_returns_dungeon_agent(self):
        """Moving from wilderness to dungeon triggers WildernessAgent -> DungeonAgent handoff."""
        from dungeon_agent import DungeonAgent
        from movement_tools import _move_player_impl

        wilderness_loc = {
            "id": "greyvale_wilderness_north",
            "name": "Northern Wilderness",
            "region_type": "wilderness",
            "exits": {"east": {"destination": "greyvale_ruins_entrance"}},
        }
        dungeon_loc = {
            "id": "greyvale_ruins_entrance",
            "name": "Ruins Entrance",
            "region_type": "dungeon",
            "description": "Cold stone steps descend into darkness.",
            "atmosphere": "oppressive, damp",
            "exits": {"west": {"destination": "greyvale_wilderness_north"}},
        }

        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_db.transaction = lambda: mock_txn(mock_conn)
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
        mock_content.get_location = AsyncMock(
            side_effect=lambda loc_id: {
                "greyvale_wilderness_north": wilderness_loc,
                "greyvale_ruins_entrance": dungeon_loc,
            }.get(loc_id)
        )

        ctx = MagicMock()
        session = SessionData(player_id="player_1", location_id="greyvale_wilderness_north")
        ctx.userdata = session

        with patch("movement_tools.publish_game_event", new_callable=AsyncMock):
            result = await _move_player_impl(
                ctx,
                "greyvale_ruins_entrance",
                db_mod=mock_db,
                mutations=mock_mutations,
                queries=mock_queries,
                content=mock_content,
            )

        assert isinstance(result, tuple)
        agent, _ = result
        assert isinstance(agent, DungeonAgent)

    @pytest.mark.asyncio
    async def test_dungeon_to_wilderness_returns_wilderness_agent(self):
        """Moving from dungeon to exterior triggers DungeonAgent -> WildernessAgent handoff."""
        from movement_tools import _move_player_impl
        from wilderness_agent import WildernessAgent

        dungeon_loc = {
            "id": "greyvale_ruins_entrance",
            "name": "Ruins Entrance",
            "region_type": "dungeon",
            "exits": {"west": {"destination": "greyvale_ruins_exterior"}},
        }
        exterior_loc = {
            "id": "greyvale_ruins_exterior",
            "name": "Ruins Exterior",
            "region_type": "wilderness",
            "description": "Wildflowers grow among broken stone.",
            "atmosphere": "windswept, open",
            "exits": {"east": {"destination": "greyvale_ruins_entrance"}},
        }

        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_db.transaction = lambda: mock_txn(mock_conn)
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
        mock_content.get_location = AsyncMock(
            side_effect=lambda loc_id: {
                "greyvale_ruins_entrance": dungeon_loc,
                "greyvale_ruins_exterior": exterior_loc,
            }.get(loc_id)
        )

        ctx = MagicMock()
        session = SessionData(player_id="player_1", location_id="greyvale_ruins_entrance")
        ctx.userdata = session

        with patch("movement_tools.publish_game_event", new_callable=AsyncMock):
            result = await _move_player_impl(
                ctx,
                "greyvale_ruins_exterior",
                db_mod=mock_db,
                mutations=mock_mutations,
                queries=mock_queries,
                content=mock_content,
            )

        assert isinstance(result, tuple)
        agent, _ = result
        assert isinstance(agent, WildernessAgent)


class TestRegionHandoffContext:
    """Verify that region-change handoffs pass rich narration context."""

    @pytest.mark.asyncio
    async def test_region_handoff_context_includes_location_name(self):
        """Handoff chat_ctx should include the destination location name."""
        from movement_tools import _move_player_impl

        city_loc = {
            "id": "accord_market_square",
            "name": "Market Square",
            "region_type": "city",
            "exits": {"south": {"destination": "greyvale_south_road"}},
        }
        wilderness_loc = {
            "id": "greyvale_south_road",
            "name": "Greyvale South Road",
            "region_type": "wilderness",
            "description": "A dusty road heading south through open grassland.",
            "atmosphere": "windswept, open sky",
            "exits": {"north": {"destination": "accord_market_square"}},
        }

        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_db.transaction = lambda: mock_txn(mock_conn)
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
        mock_content.get_location = AsyncMock(
            side_effect=lambda loc_id: {
                "accord_market_square": city_loc,
                "greyvale_south_road": wilderness_loc,
            }.get(loc_id)
        )

        ctx = MagicMock()
        session = SessionData(player_id="player_1", location_id="accord_market_square")
        ctx.userdata = session

        with patch("movement_tools.publish_game_event", new_callable=AsyncMock):
            result = await _move_player_impl(
                ctx,
                "greyvale_south_road",
                db_mod=mock_db,
                mutations=mock_mutations,
                queries=mock_queries,
                content=mock_content,
            )

        assert isinstance(result, tuple)
        agent, _ = result
        ctx_items = agent.chat_ctx.items
        system_msgs = [item for item in ctx_items if item.role == "system"]
        assert len(system_msgs) > 0
        msg = system_msgs[0]
        content = msg.content[0].text if hasattr(msg.content[0], "text") else str(msg.content[0])
        assert "Greyvale South Road" in content

    @pytest.mark.asyncio
    async def test_region_handoff_context_includes_companion(self):
        """Handoff chat_ctx should mention companion if present."""
        from movement_tools import _move_player_impl

        city_loc = {
            "id": "accord_market_square",
            "name": "Market Square",
            "region_type": "city",
            "exits": {"south": {"destination": "greyvale_south_road"}},
        }
        wilderness_loc = {
            "id": "greyvale_south_road",
            "name": "Greyvale South Road",
            "region_type": "wilderness",
            "description": "A dusty road.",
            "atmosphere": "windswept",
            "exits": {},
        }

        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_db.transaction = lambda: mock_txn(mock_conn)
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
        mock_content.get_location = AsyncMock(
            side_effect=lambda loc_id: {
                "accord_market_square": city_loc,
                "greyvale_south_road": wilderness_loc,
            }.get(loc_id)
        )

        ctx = MagicMock()
        session = SessionData(player_id="player_1", location_id="accord_market_square")
        session.companion = CompanionState(id="companion_kael", name="Kael")
        ctx.userdata = session

        with patch("movement_tools.publish_game_event", new_callable=AsyncMock):
            result = await _move_player_impl(
                ctx,
                "greyvale_south_road",
                db_mod=mock_db,
                mutations=mock_mutations,
                queries=mock_queries,
                content=mock_content,
            )

        assert isinstance(result, tuple)
        agent, _ = result
        ctx_items = agent.chat_ctx.items
        system_msgs = [item for item in ctx_items if item.role == "system"]
        content = (
            system_msgs[0].content[0].text
            if hasattr(system_msgs[0].content[0], "text")
            else str(system_msgs[0].content[0])
        )
        assert "Kael" in content
