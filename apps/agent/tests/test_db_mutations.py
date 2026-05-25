"""Tests for the story-004 crafting write producers in db_mutations.

Pass a mock conn directly (the functions accept conn=) and assert the SQL +
params. Real SQL is exercised against a testcontainer at the capstone (ADR 0003).
"""

import json
from unittest.mock import AsyncMock

import pytest

import db_mutations


class TestCreateWorkspaceRental:
    async def test_inserts_rental_and_returns_rent_id(self):
        conn = AsyncMock()
        rid = await db_mutations.create_workspace_rental("p1", "millhaven", "forge", "rental", None, conn=conn)
        assert rid.startswith("rent_")
        sql, *params = conn.execute.call_args.args
        assert "INSERT INTO workspace_rentals" in sql
        # id, player_id, location_id, workspace_type, source, expires_at
        assert params == [rid, "p1", "millhaven", "forge", "rental", None]


class TestConsumePlayerMaterials:
    async def test_decrements_when_remaining_positive(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=3)
        await db_mutations.consume_player_materials("p1", {"iron_ore": 2}, conn=conn)
        sql = conn.execute.call_args.args[0]
        assert "UPDATE player_inventory" in sql and "jsonb_set" in sql

    async def test_deletes_when_fully_consumed(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=2)
        await db_mutations.consume_player_materials("p1", {"iron_ore": 2}, conn=conn)
        sql = conn.execute.call_args.args[0]
        assert "DELETE FROM player_inventory" in sql

    async def test_consumes_each_material_in_allocation(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=5)
        await db_mutations.consume_player_materials("p1", {"iron_ore": 1, "oak_wood": 2}, conn=conn)
        assert conn.execute.await_count == 2

    async def test_raises_on_short_stack_instead_of_deleting(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=1)
        with pytest.raises(ValueError, match="exceeds held quantity"):
            await db_mutations.consume_player_materials("p1", {"iron_ore": 2}, conn=conn)
        conn.execute.assert_not_awaited()


class TestUpdatePlayerGold:
    async def test_sets_gold_via_jsonb(self):
        conn = AsyncMock()
        await db_mutations.update_player_gold("p1", 12.5, conn=conn)
        sql, *params = conn.execute.call_args.args
        assert "UPDATE players" in sql and "'{gold}'" in sql
        assert params[0] == "p1"
        assert json.loads(params[1]) == 12.5


class TestCreateAsyncActivityConnSeam:
    async def test_uses_injected_conn_without_pool(self):
        conn = AsyncMock()
        aid = await db_mutations.create_async_activity("p1", {"status": "in_progress"}, conn=conn)
        assert aid.startswith("activity_")
        conn.execute.assert_awaited_once()
