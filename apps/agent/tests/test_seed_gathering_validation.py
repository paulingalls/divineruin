"""M4.8 story-015: seed-time fail-loud validation for gathering_nodes + resource_table refs.

scripts/seed_content.validate() fails the seed loudly on bad cross-references (loot_tables already
did; gathering did not). A gathering_node whose location_id / resource_type — or a location's
resource_table entry — doesn't resolve must surface as a validation error, so a content typo can't
ship a node that grants a nonexistent material or sits at a nonexistent place.

Unit-tests validate() with a fake conn (no DB), mirroring the loot_tables fail-loud contract.
scripts/ isn't on the fast-lane pythonpath, so add it the way the acceptance conftest does.
"""

import json
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import seed_content  # type: ignore[import-not-found]  # noqa: E402


class _FakeConn:
    """Dispatches fetch() by the table named in 'FROM <table>'; unconfigured tables return []."""

    def __init__(self, tables: dict[str, list[dict]]):
        self._tables = tables

    async def fetch(self, sql: str, *args):
        for name, rows in self._tables.items():
            if f"FROM {name}" in sql:
                return rows
        return []


def _loc(loc_id: str, *, resource_table=None) -> dict:
    data: dict = {"id": loc_id, "exits": {}}
    if resource_table is not None:
        data["resource_table"] = resource_table
    return {"id": loc_id, "data": json.dumps(data)}


def _node(node_id: str, *, location_id: str, resource_type: str) -> dict:
    return {
        "id": node_id,
        "data": json.dumps({"id": node_id, "location_id": location_id, "resource_type": resource_type}),
    }


def _base_tables(nodes: list[dict], *, resource_table=None) -> dict[str, list[dict]]:
    # A single valid location + a 2-material catalog; only gathering rows vary per test.
    return {
        "locations": [_loc("greyvale_north", resource_table=resource_table)],
        "materials_catalog": [{"id": "medicinal_herb"}, {"id": "iron_ore"}],
        "gathering_nodes": nodes,
    }


async def test_clean_gathering_refs_produce_no_errors():
    conn = _FakeConn(_base_tables([_node("n1", location_id="greyvale_north", resource_type="medicinal_herb")]))
    errors = await seed_content.validate(conn)
    assert errors == []


async def test_unknown_resource_type_is_flagged():
    conn = _FakeConn(_base_tables([_node("n_bad", location_id="greyvale_north", resource_type="moon_cheese")]))
    errors = await seed_content.validate(conn)
    assert any("n_bad" in e and "moon_cheese" in e for e in errors), errors


async def test_unknown_location_id_is_flagged():
    conn = _FakeConn(_base_tables([_node("n_loc", location_id="nowhere", resource_type="iron_ore")]))
    errors = await seed_content.validate(conn)
    assert any("n_loc" in e and "nowhere" in e for e in errors), errors


async def test_unknown_resource_table_material_is_flagged():
    conn = _FakeConn(
        _base_tables(
            [_node("n1", location_id="greyvale_north", resource_type="iron_ore")],
            resource_table={"common": ["medicinal_herb"], "rare": ["unobtanium"]},
        )
    )
    errors = await seed_content.validate(conn)
    assert any("greyvale_north" in e and "unobtanium" in e for e in errors), errors
