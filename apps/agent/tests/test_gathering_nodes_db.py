"""Real-PG round-trip for the M4.6c gathering_nodes table (story-002, migration 056).

Single-table round-trip against the shared dev DB at :55432 (fast lane; conftest auto-starts
docker). Proves AC#1 — the gathering_nodes (id, data JSONB) row persists the node's
location_id / node_type / resource_type / quantity / discovered / respawn_days fields — and the
quantity-deplete / discovered-set jsonb_set mutations story-003 will issue. Isolates via a
unique id + cleanup (the _db_lifecycle / dev_db_pool pattern).
"""

import json
import uuid

import pytest

import db

pytestmark = pytest.mark.usefixtures("dev_db_pool")


async def _delete_node(node_id: str) -> None:
    pool = await db.get_pool()
    await pool.execute("DELETE FROM gathering_nodes WHERE id = $1", node_id)


async def test_node_row_round_trips_all_data_fields():
    pool = await db.get_pool()
    node_id = f"test_node_{uuid.uuid4().hex}"
    data = {
        "location_id": "greyvale_wilderness_north",
        "node_type": "herb_garden",
        "resource_type": "medicinal_herb",
        "quantity": 3,
        "discovered": False,
        "respawn_days": 2,
    }
    try:
        await pool.execute("INSERT INTO gathering_nodes (id, data) VALUES ($1, $2)", node_id, json.dumps(data))
        row = await pool.fetchrow("SELECT data FROM gathering_nodes WHERE id = $1", node_id)
        assert row is not None
        assert json.loads(row["data"]) == data
    finally:
        await _delete_node(node_id)


async def test_deplete_quantity_and_mark_discovered_via_jsonb_set():
    # The two mutations story-003's consumer will issue against a fixed node.
    pool = await db.get_pool()
    node_id = f"test_node_{uuid.uuid4().hex}"
    data = {
        "location_id": "greyvale_ruins_entrance",
        "node_type": "salvage_site",
        "resource_type": "iron_ore",
        "quantity": 2,
        "discovered": False,
        "respawn_days": 0,
    }
    try:
        await pool.execute("INSERT INTO gathering_nodes (id, data) VALUES ($1, $2)", node_id, json.dumps(data))
        await pool.execute(
            "UPDATE gathering_nodes SET data = jsonb_set("
            "jsonb_set(data, '{discovered}', 'true'::jsonb), '{quantity}', '1'::jsonb) "
            "WHERE id = $1",
            node_id,
        )
        row = await pool.fetchrow("SELECT data FROM gathering_nodes WHERE id = $1", node_id)
        out = json.loads(row["data"])
        assert out["discovered"] is True
        assert out["quantity"] == 1
    finally:
        await _delete_node(node_id)


async def test_seeded_fixed_nodes_present():
    # The content/gathering_nodes.json seed loads into the table (server/seed pipeline).
    pool = await db.get_pool()
    row = await pool.fetchrow("SELECT data FROM gathering_nodes WHERE id = $1", "greyvale_north_herb_garden")
    assert row is not None, "expected seeded node greyvale_north_herb_garden"
    assert json.loads(row["data"])["node_type"] == "herb_garden"
