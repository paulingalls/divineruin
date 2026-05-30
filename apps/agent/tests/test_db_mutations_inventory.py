"""Tests for inventory item-instance-state writes (db_mutations_inventory).

Pass a mock conn directly (the function accepts conn=) and assert the SQL +
params. Real SQL is exercised against a testcontainer at the capstone (ADR 0003).
"""

import json
from unittest.mock import AsyncMock

import db_mutations_inventory


class TestUpdateItemDurability:
    async def test_sets_current_hits_via_jsonb_keyed_by_player_and_item(self):
        conn = AsyncMock()
        await db_mutations_inventory.update_item_durability("p1", "longsword_guild", 7, conn=conn)
        sql, *params = conn.execute.call_args.args
        assert "UPDATE player_inventory" in sql
        assert "jsonb_set" in sql and "'{current_hits}'" in sql
        assert "WHERE player_id = $1 AND item_id = $2" in sql
        assert params[0] == "p1"
        assert params[1] == "longsword_guild"
        assert json.loads(params[2]) == 7

    async def test_uses_injected_conn_without_pool(self):
        conn = AsyncMock()
        await db_mutations_inventory.update_item_durability("p1", "shield_iron", 0, conn=conn)
        conn.execute.assert_awaited_once()
