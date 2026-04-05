"""Tests for async activity database functions."""

import json
from unittest.mock import AsyncMock, patch

import pytest

import db_mutations
import db_queries


class TestCreateAsyncActivity:
    @pytest.mark.asyncio
    async def test_creates_activity_and_returns_id(self):
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()

        with patch("db.get_pool", return_value=mock_pool):
            activity_id = await db_mutations.create_async_activity(
                "p1", {"status": "in_progress", "activity_type": "crafting"}
            )

        assert activity_id.startswith("activity_")
        mock_pool.execute.assert_awaited_once()
        call_args = mock_pool.execute.call_args[0]
        assert "INSERT INTO async_activities" in call_args[0]
        assert call_args[1] == activity_id
        assert call_args[2] == "p1"
        data = json.loads(call_args[3])
        assert data["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_unique_ids(self):
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()

        with patch("db.get_pool", return_value=mock_pool):
            id1 = await db_mutations.create_async_activity("p1", {"status": "in_progress"})
            id2 = await db_mutations.create_async_activity("p1", {"status": "in_progress"})

        assert id1 != id2


class TestGetPlayerActivities:
    @pytest.mark.asyncio
    async def test_returns_all_activities(self):
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(
            return_value=[
                {"id": "act_1", "data": json.dumps({"status": "in_progress", "activity_type": "crafting"})},
                {"id": "act_2", "data": json.dumps({"status": "resolved", "activity_type": "training"})},
            ]
        )

        with patch("db.get_pool", return_value=mock_pool):
            result = await db_queries.get_player_activities("p1")

        assert len(result) == 2
        assert result[0]["id"] == "act_1"
        assert result[0]["status"] == "in_progress"
        assert result[1]["id"] == "act_2"

    @pytest.mark.asyncio
    async def test_filters_by_status(self):
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(
            return_value=[
                {"id": "act_1", "data": json.dumps({"status": "resolved"})},
            ]
        )

        with patch("db.get_pool", return_value=mock_pool):
            result = await db_queries.get_player_activities("p1", status="resolved")

        assert len(result) == 1
        call_args = mock_pool.fetch.call_args[0]
        assert "data->>'status' = $2" in call_args[0]
        assert call_args[2] == "resolved"

    @pytest.mark.asyncio
    async def test_empty_result(self):
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[])

        with patch("db.get_pool", return_value=mock_pool):
            result = await db_queries.get_player_activities("p1")

        assert result == []

    @pytest.mark.asyncio
    async def test_uses_provided_conn(self):
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])

        result = await db_queries.get_player_activities("p1", conn=mock_conn)
        assert result == []
        mock_conn.fetch.assert_awaited_once()


class TestGetActivity:
    @pytest.mark.asyncio
    async def test_returns_activity(self):
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(
            return_value={
                "id": "act_1",
                "player_id": "p1",
                "data": json.dumps({"status": "in_progress", "activity_type": "crafting"}),
            }
        )

        with patch("db.get_pool", return_value=mock_pool):
            result = await db_queries.get_activity("act_1")

        assert result["id"] == "act_1"
        assert result["player_id"] == "p1"
        assert result["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value=None)

        with patch("db.get_pool", return_value=mock_pool):
            result = await db_queries.get_activity("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_for_update_adds_lock(self):
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(
            return_value={"id": "act_1", "player_id": "p1", "data": json.dumps({"status": "in_progress"})}
        )

        with patch("db.get_pool", return_value=mock_pool):
            await db_queries.get_activity("act_1", for_update=True)

        call_args = mock_pool.fetchrow.call_args[0]
        assert "FOR UPDATE" in call_args[0]


class TestGetDueActivities:
    @pytest.mark.asyncio
    async def test_returns_due_activities(self):
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(
            return_value=[
                {
                    "id": "act_1",
                    "player_id": "p1",
                    "data": json.dumps({"status": "in_progress", "resolve_at": "2026-01-01T00:00:00Z"}),
                },
            ]
        )

        with patch("db.get_pool", return_value=mock_pool):
            result = await db_queries.get_due_activities()

        assert len(result) == 1
        assert result[0]["id"] == "act_1"
        assert result[0]["player_id"] == "p1"

    @pytest.mark.asyncio
    async def test_query_filters_by_status_and_time(self):
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[])

        with patch("db.get_pool", return_value=mock_pool):
            await db_queries.get_due_activities()

        call_args = mock_pool.fetch.call_args[0]
        assert "data->>'status' = 'in_progress'" in call_args[0]
        assert "resolve_at" in call_args[0]
        assert "NOW()" in call_args[0]


class TestUpdateActivity:
    @pytest.mark.asyncio
    async def test_updates_single_field(self):
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()

        with patch("db.get_pool", return_value=mock_pool):
            await db_mutations.update_activity("act_1", {"status": "resolved"})

        mock_pool.execute.assert_awaited_once()
        call_args = mock_pool.execute.call_args[0]
        assert "data || $2::jsonb" in call_args[0]
        assert call_args[1] == "act_1"
        merged = json.loads(call_args[2])
        assert merged["status"] == "resolved"

    @pytest.mark.asyncio
    async def test_updates_multiple_fields(self):
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()

        with patch("db.get_pool", return_value=mock_pool):
            await db_mutations.update_activity("act_1", {"status": "resolved", "outcome": {"tier": "success"}})

        # Single merged query instead of N separate calls
        mock_pool.execute.assert_awaited_once()
        call_args = mock_pool.execute.call_args[0]
        merged = json.loads(call_args[2])
        assert merged["status"] == "resolved"
        assert merged["outcome"]["tier"] == "success"

    @pytest.mark.asyncio
    async def test_uses_provided_conn(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()

        await db_mutations.update_activity("act_1", {"status": "resolved"}, conn=mock_conn)
        mock_conn.execute.assert_awaited_once()


class TestCountActiveActivities:
    @pytest.mark.asyncio
    async def test_returns_count(self):
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value={"cnt": 3})

        with patch("db.get_pool", return_value=mock_pool):
            result = await db_queries.count_active_activities("p1")

        assert result == 3

    @pytest.mark.asyncio
    async def test_returns_zero_for_no_activities(self):
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value={"cnt": 0})

        with patch("db.get_pool", return_value=mock_pool):
            result = await db_queries.count_active_activities("p1")

        assert result == 0

    @pytest.mark.asyncio
    async def test_query_filters_in_progress(self):
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value={"cnt": 0})

        with patch("db.get_pool", return_value=mock_pool):
            await db_queries.count_active_activities("p1")

        call_args = mock_pool.fetchrow.call_args[0]
        assert "data->>'status' = 'in_progress'" in call_args[0]
