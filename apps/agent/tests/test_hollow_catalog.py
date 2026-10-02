"""Catalog-wide Hollow claims from bestiary lines 132-608."""

import copy
import json
from pathlib import Path

import pytest

from creature_schema import validate_creature_stat_block

ROOT = Path(__file__).resolve().parents[3]
SPEC_IDS = {
    "hollow_shadeling",
    "hollow_hollowmoth",
    "hollow_mawling",
    "hollow_weaver",
    "hollow_knight",
    "hollow_veilrender",
    "hollow_choir",
    "hollow_still",
    "hollow_architect",
}


def hollow_rows():
    return [row for row in json.loads((ROOT / "content/creatures.json").read_text()) if row["category"] == "hollow"]


def assert_complete(rows):
    for creature_id in SPEC_IDS:
        matches = [row for row in rows if row["id"] == creature_id]
        assert len(matches) == 1, creature_id
        row = matches[0]
        assert validate_creature_stat_block(row) == [], creature_id
        hollow = row.get("hollow")
        assert isinstance(hollow, dict), creature_id
        assert hollow.get("class") in {"drift", "rend", "wrack", "named"}
        assert type(hollow.get("corruption_aura")) is int
        assert type(hollow.get("resonance_on_death")) is int
        assert hollow.get("veil_effect", "").strip()
        assert hollow.get("vulnerable_to")


def assert_distinct(rows):
    assert rows, "Hollow catalog is empty"
    ids = [row["id"] for row in rows]
    veils = [row["hollow"]["veil_effect"].strip() for row in rows]
    vulnerabilities = [frozenset(row["hollow"]["vulnerable_to"]) for row in rows]
    assert len(ids) == len(set(ids))
    assert all(veils)
    assert all(vulnerabilities)
    assert len(veils) == len(set(veils))
    assert len(vulnerabilities) == len(set(vulnerabilities))


def test_all_spec_hollow_ids_have_complete_blocks():
    assert_complete(hollow_rows())


def test_all_hollow_veil_effects_and_vulnerabilities_are_pairwise_distinct():
    assert_distinct(hollow_rows())


def test_hollow_walks_reject_missing_null_copied_and_empty():
    rows = hollow_rows()
    missing = [row for row in rows if row["id"] != "hollow_shadeling"]
    with pytest.raises(AssertionError):
        assert_complete(missing)
    null = copy.deepcopy(rows)
    next(row for row in null if row["id"] == "hollow_shadeling")["hollow"] = None
    with pytest.raises(AssertionError):
        assert_complete(null)
    for key in ("veil_effect", "vulnerable_to"):
        copied = copy.deepcopy(rows)
        copied[1]["hollow"][key] = copied[0]["hollow"][key]
        with pytest.raises(AssertionError):
            assert_distinct(copied)
    with pytest.raises(AssertionError):
        assert_distinct([])
