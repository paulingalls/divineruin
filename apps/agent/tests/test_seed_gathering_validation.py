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
    content = Path(__file__).resolve().parents[3] / "content"
    encounter = json.loads((content / "encounter_templates.json").read_text())[0]
    creature_ids = {enemy["creature_id"] for enemy in encounter["enemies"]}
    creatures = [row for row in json.loads((content / "creatures.json").read_text()) if row["id"] in creature_ids]
    loot_ids = {row["loot_table_id"] for row in creatures}
    loot = [row for row in json.loads((content / "loot_tables.json").read_text()) if row["id"] in loot_ids]
    drop_ids = {drop["item_id"] for row in loot for drop in row["drops"]}
    items = json.loads((content / "items.json").read_text())
    materials = json.loads((content / "materials_catalog.json").read_text())
    return {
        "encounter_templates": [{"id": encounter["id"], "data": json.dumps(encounter)}],
        "creatures": [{"id": row["id"], "data": json.dumps(row)} for row in creatures],
        "loot_tables": [{"id": row["id"], "data": json.dumps(row)} for row in loot],
        "items": [{"id": row["id"]} for row in items if row["id"] in drop_ids],
        "locations": [_loc("greyvale_north", resource_table=resource_table)],
        "materials_catalog": [{"id": "medicinal_herb"}, {"id": "iron_ore"}]
        + [{"id": row["id"]} for row in materials if row["id"] in drop_ids],
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
