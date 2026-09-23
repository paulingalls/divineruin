"""Conformance of authored loot tables and seed-time loot validation."""

import copy
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "scripts"))
import seed_content  # type: ignore[import-not-found]  # noqa: E402


def _table() -> dict:
    return {"id": "loot_probe", "drops": [{"item_id": "probe_item", "chance": 1.0, "quantity": 1}]}


@pytest.mark.parametrize("drops", [None, [], "missing"])
def test_empty_or_missing_drops_are_refused(drops) -> None:
    table = _table()
    if drops == "missing":
        del table["drops"]
    else:
        table["drops"] = drops
    assert any("loot_probe" in error and "drops" in error for error in seed_content.validate_loot_table(table))


def test_authored_loot_corpus_conforms() -> None:
    path = _ROOT / "content" / "loot_tables.json"
    assert path.is_file(), path
    tables = json.loads(path.read_text())
    assert tables, "empty loot corpus"
    assert all(table.get("drops") for table in tables), "empty loot table"
    assert [error for table in tables for error in seed_content.validate_loot_table(table)] == []


@pytest.mark.parametrize(
    "change,fragment",
    [
        ({"requires": "Crafting: Expert"}, "requires"),
        ({"requires": [{"skill": "alchemy", "tier": "expert"}]}, "skill"),
        ({"requires": [{"skill": "crafting", "tier": "legendary"}]}, "tier"),
        ({"requires": [{"skill": "Crafting", "tier": "expert"}]}, "skill"),
        ({"requires": ["crafting:expert"]}, "requires"),
        ({"requires": [{"skill": "crafting"}]}, "requires"),
        ({"requires": [{"skill": "crafting", "tier": "expert", "note": "x"}]}, "requires"),
        ({"chance": 1.5}, "chance"),
        ({"chance": "0.5"}, "chance"),
        ({"quantity": 0}, "quantity"),
        ({"quantity": True}, "quantity"),
        ({"quantity": "bad"}, "quantity"),
        ({"quantity": "1d4-4"}, "quantity"),
    ],
)
def test_bad_drop_is_refused_with_table_and_item(change: dict, fragment: str) -> None:
    table = _table()
    table["drops"][0].update(change)
    errors = seed_content.validate_loot_table(table)
    assert any("loot_probe" in e and "probe_item" in e and fragment in e for e in errors), errors


def test_compound_requirement_and_dice_quantity_conform() -> None:
    table = _table()
    table["drops"][0].update(
        {
            "quantity": "1d4",
            "requires": [{"skill": "crafting", "tier": "expert"}, {"skill": "arcana", "tier": "trained"}],
        }
    )
    assert seed_content.validate_loot_table(table) == []


def test_bad_hollow_residue_flag_is_refused() -> None:
    table = _table()
    table["hollow_residue"] = "true"
    assert any("loot_probe" in e and "hollow_residue" in e for e in seed_content.validate_loot_table(table))


def test_residue_tables_pin_authored_requirements() -> None:
    tables = {table["id"]: table for table in json.loads((_ROOT / "content" / "loot_tables.json").read_text())}
    residues = {
        "loot_hollow_drift": "hollow_residue_t1",
        "loot_hollow_rend": "hollow_residue_t1",
        "loot_hollowed_knight": "hollow_residue_t2",
    }
    for table_id, item_id in residues.items():
        table = tables[table_id]
        assert table["hollow_residue"] is True
        residue = next(drop for drop in table["drops"] if drop["item_id"] == item_id)
        assert residue["requires"] == [{"skill": "crafting", "tier": "expert"}]


class _Connection:
    def __init__(self, table: dict):
        self.table = table

    async def fetch(self, sql: str, *args):
        if "FROM loot_tables" in sql:
            return [{"id": self.table["id"], "data": json.dumps(self.table)}]
        if "FROM items" in sql:
            return [{"id": "probe_item"}, {"id": "crystal_flask"}]
        if "FROM materials_catalog" in sql:
            return [{"id": "iron_ore"}, {"id": "crystal_flask"}]
        return []


@pytest.mark.parametrize(
    "drop_id,expected",
    [("probe_item", None), ("iron_ore", None), ("missing_drop", "unknown"), ("crystal_flask", "ambiguous")],
)
async def test_seed_loot_drop_has_exactly_one_catalog(drop_id: str, expected: str | None) -> None:
    table = _table()
    table["drops"][0]["item_id"] = drop_id
    errors = await seed_content.validate(_Connection(table))
    loot_errors = [error for error in errors if "Loot table 'loot_probe'" in error]
    if expected:
        assert any(drop_id in error and expected in error for error in loot_errors), loot_errors
    else:
        assert loot_errors == []


@pytest.mark.parametrize(
    "change",
    [
        {"requires": "crafting:expert"},
        {"requires": [{"skill": "missing", "tier": "expert"}]},
        {"requires": [{"skill": "crafting", "tier": "missing"}]},
    ],
)
async def test_seed_refuses_bad_requirement(change: dict) -> None:
    table = copy.deepcopy(_table())
    table["drops"][0].update(change)
    errors = await seed_content.validate(_Connection(table))
    assert any("loot_probe" in e and "probe_item" in e for e in errors), errors
