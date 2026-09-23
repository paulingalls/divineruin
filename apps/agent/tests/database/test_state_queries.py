"""Tests for non-cached state queries (player, NPC dispositions, inventory, flags)."""

import json
from unittest.mock import AsyncMock, patch

import pytest

import db_queries


class TestStateQueries:
    """Test non-cached state queries (player, NPC dispositions, inventory)."""

    @pytest.mark.asyncio
    async def test_get_player_returns_player_data(self):
        """get_player should query and return player data."""
        player_data = {"player_id": "p1", "name": "Hero", "level": 5}
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value={"data": json.dumps(player_data)})

        with patch("db.get_pool", return_value=mock_pool):
            result = await db_queries.get_player("p1")

        assert result == player_data
        mock_pool.fetchrow.assert_awaited_once_with("SELECT data FROM players WHERE player_id = $1", "p1")

    @pytest.mark.asyncio
    async def test_get_player_with_for_update_adds_lock(self):
        """get_player with for_update=True should add FOR UPDATE clause."""
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value={"data": '{"level": 5}'})

        with patch("db.get_pool", return_value=mock_pool):
            await db_queries.get_player("p1", for_update=True)

        call_args = mock_pool.fetchrow.call_args[0]
        assert "FOR UPDATE" in call_args[0]

    @pytest.mark.asyncio
    async def test_get_npc_disposition_returns_disposition(self):
        """get_npc_disposition should return disposition string."""
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(
            return_value={"data": json.dumps({"disposition": "friendly", "reason": "helped"})}
        )

        with patch("db.get_pool", return_value=mock_pool):
            result = await db_queries.get_npc_disposition("torin", "p1")

        assert result == "friendly"

    @pytest.mark.asyncio
    async def test_get_npc_dispositions_batch_fetches(self):
        """get_npc_dispositions should batch-fetch multiple NPCs."""
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(
            return_value=[
                {"npc_id": "npc1", "data": json.dumps({"disposition": "friendly"})},
                {"npc_id": "npc2", "data": json.dumps({"disposition": "hostile"})},
            ]
        )

        with patch("db.get_pool", return_value=mock_pool):
            result = await db_queries.get_npc_dispositions(["npc1", "npc2"], "p1")

        assert result == {"npc1": "friendly", "npc2": "hostile"}

    @pytest.mark.asyncio
    async def test_get_npc_dispositions_empty_list_returns_empty_dict(self):
        """get_npc_dispositions with empty list should return empty dict."""
        result = await db_queries.get_npc_dispositions([], "p1")
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_player_inventory_joins_items(self):
        """get_player_inventory should join items and inventory slots."""
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(
            return_value=[
                {
                    "item_data": json.dumps({"id": "sword", "name": "Steel Sword"}),
                    "slot_data": json.dumps({"quantity": 1, "equipped": True}),
                }
            ]
        )

        with patch("db.get_pool", return_value=mock_pool):
            result = await db_queries.get_player_inventory("p1")

        assert len(result) == 1
        assert result[0]["id"] == "sword"
        assert result[0]["slot_info"]["equipped"] is True

    @pytest.mark.asyncio
    async def test_get_npcs_at_location_queries_schedule(self):
        """get_npcs_at_location should query NPCs by schedule."""
        npc_data = {"id": "torin", "name": "Torin", "schedule": {"evening": "tavern"}}
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[{"id": "torin", "data": json.dumps(npc_data)}])

        with patch("db.get_pool", return_value=mock_pool):
            result = await db_queries.get_npcs_at_location("tavern")

        assert len(result) == 1
        assert result[0]["id"] == "torin"
        assert result[0]["name"] == "Torin"

    @pytest.mark.asyncio
    async def test_get_active_player_quests_joins_quest_data(self):
        """get_active_player_quests should join player quest state with quest data."""
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(
            return_value=[
                {
                    "quest_id": "q1",
                    "pq_data": json.dumps({"current_stage": 2}),
                    "q_data": json.dumps(
                        {
                            "name": "The Quest",
                            "stages": ["stage1", "stage2", "stage3"],
                        }
                    ),
                }
            ]
        )

        with patch("db.get_pool", return_value=mock_pool):
            result = await db_queries.get_active_player_quests("p1")

        assert len(result) == 1
        assert result[0]["quest_id"] == "q1"
        assert result[0]["quest_name"] == "The Quest"
        assert result[0]["current_stage"] == 2
        assert len(result[0]["stages"]) == 3

    @pytest.mark.asyncio
    async def test_get_active_player_quests_includes_scene_graph(self):
        """get_active_player_quests should include scene_graph when present."""
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(
            return_value=[
                {
                    "quest_id": "q1",
                    "pq_data": json.dumps({"current_stage": 0}),
                    "q_data": json.dumps(
                        {
                            "name": "Quest With Graph",
                            "stages": [{"id": "s0"}],
                            "scene_graph": [{"scene_id": "scene_a", "stage_refs": [0]}],
                        }
                    ),
                }
            ]
        )

        with patch("db.get_pool", return_value=mock_pool):
            result = await db_queries.get_active_player_quests("p1")

        assert result[0]["scene_graph"] == [{"scene_id": "scene_a", "stage_refs": [0]}]


class TestGetPlayerFlagValue:
    @pytest.mark.asyncio
    async def test_returns_int(self):
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value={"val": "3"})
        with patch("db.get_pool", new_callable=AsyncMock, return_value=mock_pool):
            result = await db_queries.get_player_flag_value("p1", "onboarding_beat")
        assert result == 3
        assert isinstance(result, int)

    @pytest.mark.asyncio
    async def test_returns_bool_true(self):
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value={"val": "true"})
        with patch("db.get_pool", new_callable=AsyncMock, return_value=mock_pool):
            result = await db_queries.get_player_flag_value("p1", "companion_met")
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_bool_false(self):
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value={"val": "false"})
        with patch("db.get_pool", new_callable=AsyncMock, return_value=mock_pool):
            result = await db_queries.get_player_flag_value("p1", "some_flag")
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_string(self):
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value={"val": '"hello"'})
        with patch("db.get_pool", new_callable=AsyncMock, return_value=mock_pool):
            result = await db_queries.get_player_flag_value("p1", "greeting")
        assert result == "hello"
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_returns_none_when_missing(self):
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value={"val": None})
        with patch("db.get_pool", new_callable=AsyncMock, return_value=mock_pool):
            result = await db_queries.get_player_flag_value("p1", "nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_row(self):
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value=None)
        with patch("db.get_pool", new_callable=AsyncMock, return_value=mock_pool):
            result = await db_queries.get_player_flag_value("p1", "any_flag")
        assert result is None
