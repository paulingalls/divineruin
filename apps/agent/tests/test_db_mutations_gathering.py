"""Tests for the gathering_nodes DB layer (M4.6c, story-003).

Mock-conn tests: pass an AsyncMock conn directly and assert the SQL + params — exercising the
jsonb_set deplete/discover mutations and the location-scoped node read. Real SQL is exercised
by tests/test_gathering_nodes_db.py (story-002's round-trip). Mirrors test_db_mutations_veil_ward.
"""

import json
from unittest.mock import AsyncMock

import db_content_queries
import db_mutations_gathering


class TestMarkNodeDiscovered:
    async def test_sets_discovered_true_via_jsonb_set(self):
        conn = AsyncMock()
        await db_mutations_gathering.mark_node_discovered("node_1", conn=conn)
        sql, *params = conn.execute.call_args.args
        assert "UPDATE gathering_nodes" in sql
        assert "jsonb_set" in sql
        assert "'{discovered}'" in sql
        assert "true" in sql
        assert params == ["node_1"]


class TestDepleteNodeQuantity:
    async def test_decrements_quantity_floored_at_zero(self):
        conn = AsyncMock()
        await db_mutations_gathering.deplete_node_quantity("node_1", 2, conn=conn)
        sql, *params = conn.execute.call_args.args
        assert "UPDATE gathering_nodes" in sql
        assert "jsonb_set" in sql
        assert "'{quantity}'" in sql
        assert "GREATEST(0" in sql  # never goes negative
        assert "quantity" in sql
        assert params == ["node_1", 2]


class TestRestoreNodeQuantity:
    async def test_restores_capped_at_capacity_via_jsonb_set(self):
        conn = AsyncMock()
        await db_mutations_gathering.restore_node_quantity("node_1", 3, conn=conn)
        sql, *params = conn.execute.call_args.args
        assert "UPDATE gathering_nodes" in sql
        assert "jsonb_set" in sql
        assert "'{quantity}'" in sql
        assert "LEAST" in sql
        assert "COALESCE" in sql
        assert "'capacity'" in sql
        assert params == ["node_1", 3]


class TestGetGatheringNodesAtLocation:
    async def test_queries_by_location_id_and_parses_rows(self):
        pool = AsyncMock()
        pool.fetch.return_value = [
            {"id": "n1", "data": json.dumps({"location_id": "loc_a", "node_type": "ore_vein", "quantity": 3})},
            {"id": "n2", "data": json.dumps({"location_id": "loc_a", "node_type": "herb_garden", "quantity": 0})},
        ]
        out = await db_content_queries.get_gathering_nodes_at_location("loc_a", pool=pool)
        sql, *params = pool.fetch.call_args.args
        assert "FROM gathering_nodes" in sql
        assert "data->>'location_id'" in sql
        assert params == ["loc_a"]
        assert out == [
            {"id": "n1", "location_id": "loc_a", "node_type": "ore_vein", "quantity": 3},
            {"id": "n2", "location_id": "loc_a", "node_type": "herb_garden", "quantity": 0},
        ]
