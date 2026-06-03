"""Tests for state mutation functions and skill advancement."""

import json
from unittest.mock import AsyncMock, patch

import pytest

import db_activity_queries
import db_mutations
import db_queries


class TestStateMutations:
    """Test state mutation functions."""

    @pytest.mark.asyncio
    async def test_update_player_location_updates_jsonb(self):
        """update_player_location should update location_id field."""
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()

        with patch("db.get_pool", return_value=mock_pool):
            await db_mutations.update_player_location("p1", "tavern")

        mock_pool.execute.assert_awaited_once()
        call_args = mock_pool.execute.call_args[0]
        assert "jsonb_set" in call_args[0]
        assert call_args[1] == "p1"
        assert json.loads(call_args[2]) == "tavern"

    @pytest.mark.asyncio
    async def test_update_player_xp_updates_both_fields(self):
        """update_player_xp should update both xp and level."""
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()

        with patch("db.get_pool", return_value=mock_pool):
            await db_mutations.update_player_xp("p1", new_xp=1000, new_level=5)

        call_args = mock_pool.execute.call_args[0]
        assert call_args[1] == "p1"
        assert json.loads(call_args[2]) == 1000
        assert json.loads(call_args[3]) == 5

    @pytest.mark.asyncio
    async def test_add_inventory_item_upserts_quantity(self):
        """add_inventory_item should insert or increment quantity."""
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()

        with patch("db.get_pool", return_value=mock_pool):
            await db_mutations.add_inventory_item("p1", "sword", quantity=2)

        call_args = mock_pool.execute.call_args[0]
        assert "INSERT INTO player_inventory" in call_args[0]
        assert "ON CONFLICT" in call_args[0]
        assert call_args[1] == "p1"
        assert call_args[2] == "sword"

    @pytest.mark.asyncio
    async def test_remove_inventory_item_returns_true_on_success(self):
        """remove_inventory_item should return True if item was deleted."""
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock(return_value="DELETE 1")

        with patch("db.get_pool", return_value=mock_pool):
            result = await db_mutations.remove_inventory_item("p1", "sword")

        assert result is True

    @pytest.mark.asyncio
    async def test_remove_inventory_item_returns_false_on_miss(self):
        """remove_inventory_item should return False if item not found."""
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock(return_value="DELETE 0")

        with patch("db.get_pool", return_value=mock_pool):
            result = await db_mutations.remove_inventory_item("p1", "nonexistent")

        assert result is False

    @pytest.mark.asyncio
    async def test_set_npc_disposition_upserts_disposition(self):
        """set_npc_disposition should insert or update disposition."""
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()

        with patch("db.get_pool", return_value=mock_pool):
            await db_mutations.set_npc_disposition("npc1", "p1", "friendly", "helped us")

        call_args = mock_pool.execute.call_args[0]
        assert "INSERT INTO npc_dispositions" in call_args[0]
        assert "ON CONFLICT" in call_args[0]
        data = json.loads(call_args[3])
        assert data["disposition"] == "friendly"
        assert data["reason"] == "helped us"

    @pytest.mark.asyncio
    async def test_set_player_quest_upserts_quest_state(self):
        """set_player_quest should insert or update quest state."""
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()

        quest_data = {"current_stage": 3, "progress": "found clue"}
        with patch("db.get_pool", return_value=mock_pool):
            await db_mutations.set_player_quest("p1", "q1", quest_data)

        call_args = mock_pool.execute.call_args[0]
        assert "INSERT INTO player_quests" in call_args[0]
        assert call_args[1] == "p1"
        assert call_args[2] == "q1"
        assert json.loads(call_args[3]) == quest_data

    @pytest.mark.asyncio
    async def test_log_world_event_inserts_event(self):
        """log_world_event should insert event into log."""
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()

        event_data = {"player_id": "p1", "action": "completed quest"}
        with patch("db.get_pool", return_value=mock_pool):
            await db_mutations.log_world_event("quest_complete", event_data)

        call_args = mock_pool.execute.call_args[0]
        assert "INSERT INTO world_events_log" in call_args[0]
        assert call_args[1] == "quest_complete"
        assert json.loads(call_args[2]) == event_data

    @pytest.mark.asyncio
    async def test_upsert_map_progress_inserts_record(self):
        """upsert_map_progress should insert a map progress record."""
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()

        with patch("db.get_pool", return_value=mock_pool):
            await db_mutations.upsert_map_progress("p1", "tavern", ["market", "docks"])

        call_args = mock_pool.execute.call_args[0]
        assert "INSERT INTO player_map_progress" in call_args[0]
        assert "ON CONFLICT" in call_args[0]
        assert "DO NOTHING" in call_args[0]
        assert call_args[1] == "p1"
        assert call_args[2] == "tavern"
        data = json.loads(call_args[3])
        assert data["connections"] == ["market", "docks"]

    @pytest.mark.asyncio
    async def test_upsert_map_progress_uses_provided_conn(self):
        """upsert_map_progress should use the provided connection."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()

        await db_mutations.upsert_map_progress("p1", "tavern", [], conn=mock_conn)

        mock_conn.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_player_map_progress_returns_visited(self):
        """get_player_map_progress should return visited locations."""
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(
            return_value=[
                {"location_id": "tavern", "data": json.dumps({"connections": ["market"]})},
                {"location_id": "market", "data": json.dumps({"connections": ["tavern", "docks"]})},
            ]
        )

        with patch("db.get_pool", return_value=mock_pool):
            result = await db_activity_queries.get_player_map_progress("p1")

        assert len(result) == 2
        assert result[0]["location_id"] == "tavern"
        assert result[0]["connections"] == ["market"]
        assert result[1]["location_id"] == "market"
        assert result[1]["connections"] == ["tavern", "docks"]

    @pytest.mark.asyncio
    async def test_get_player_map_progress_empty(self):
        """get_player_map_progress should return empty list for new player."""
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[])

        with patch("db.get_pool", return_value=mock_pool):
            result = await db_activity_queries.get_player_map_progress("new_player")

        assert result == []

    @pytest.mark.asyncio
    async def test_update_player_portrait_updates_jsonb(self):
        """update_player_portrait should set portrait_url in player data."""
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()

        with patch("db.get_pool", return_value=mock_pool):
            await db_mutations.update_player_portrait("p1", "/api/assets/images/img_abc123")

        call_args = mock_pool.execute.call_args[0]
        assert "jsonb_set" in call_args[0]
        assert "portrait_url" in call_args[0]
        assert call_args[1] == "p1"
        assert json.loads(call_args[2]) == "/api/assets/images/img_abc123"


class TestSkillAdvancement:
    @pytest.mark.asyncio
    async def test_get_skill_advancement_returns_dict(self):
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(
            return_value=[
                {"skill_id": "athletics", "tier": "trained", "use_counter": 12, "narrative_moment_ready": False},
                {"skill_id": "stealth", "tier": "untrained", "use_counter": 3, "narrative_moment_ready": False},
            ]
        )
        with patch("db.get_pool", new_callable=AsyncMock, return_value=mock_pool):
            result = await db_queries.get_skill_advancement("p1")
        assert result["athletics"]["tier"] == "trained"
        assert result["athletics"]["use_counter"] == 12
        assert result["stealth"]["use_counter"] == 3

    @pytest.mark.asyncio
    async def test_get_skill_advancement_empty(self):
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[])
        with patch("db.get_pool", new_callable=AsyncMock, return_value=mock_pool):
            result = await db_queries.get_skill_advancement("p1")
        assert result == {}

    @pytest.mark.asyncio
    async def test_update_skill_advancement_upserts(self):
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()
        with patch("db.get_pool", new_callable=AsyncMock, return_value=mock_pool):
            await db_mutations.update_skill_advancement("p1", "athletics", "trained", 12)
        call_args = mock_pool.execute.call_args[0]
        assert "ON CONFLICT" in call_args[0]
        assert call_args[1] == "p1"
        assert call_args[2] == "athletics"
        assert call_args[3] == "trained"
        assert call_args[4] == 12

    @pytest.mark.asyncio
    async def test_mark_narrative_moment_sets_flag(self):
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()
        with patch("db.get_pool", new_callable=AsyncMock, return_value=mock_pool):
            await db_mutations.mark_narrative_moment("p1", "athletics")
        call_args = mock_pool.execute.call_args[0]
        assert "narrative_moment_ready" in call_args[0]
        assert "TRUE" in call_args[0]

    @pytest.mark.asyncio
    async def test_clear_narrative_moment_clears_flag(self):
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()
        with patch("db.get_pool", new_callable=AsyncMock, return_value=mock_pool):
            await db_mutations.clear_narrative_moment("p1", "athletics")
        call_args = mock_pool.execute.call_args[0]
        assert "FALSE" in call_args[0]
