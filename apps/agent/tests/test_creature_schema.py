import copy
import json
from pathlib import Path

import pytest

from conditions import CONDITION_CATALOG
from creature_schema import validate_creature_stat_block
from social_resolution import RESISTANCE_TAGS

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "packages/shared/fixtures/creature_blocks.json"
CATALOG = ROOT / "content/loot_tables.json"
CATEGORIES = {"hollow", "beast", "humanoid", "construct", "undead", "elemental"}


def assert_corpus_floors(valid, invalid):
    assert valid and invalid
    assert any(case.get("spec_derived") for case in valid)


def test_corpus_floors():
    corpus = json.loads(CORPUS.read_text())
    valid, invalid = corpus["valid"], corpus["invalid"]
    with pytest.raises(AssertionError):
        assert_corpus_floors([], invalid)
    with pytest.raises(AssertionError):
        assert_corpus_floors(valid, [])
    with pytest.raises(AssertionError):
        assert_corpus_floors([{**case, "spec_derived": None} for case in valid], invalid)


def test_shared_creature_corpus():
    assert CORPUS.is_file()
    corpus = json.loads(CORPUS.read_text())
    valid, invalid = corpus["valid"], corpus["invalid"]
    assert {case["name"] for case in invalid} >= {
        "missing_regions",
        "empty_regions",
        "unknown_region",
        "missing_home_region",
        "unknown_home_region",
        "unknown_active_kind",
        "mark_with_damage",
        "condition_without_save",
        "condition_without_dc",
        "unknown_condition",
        "half_without_damage",
        "grapple_without_escape_dc",
        "unknown_resistance_tag",
        "signature_without_name",
        "signature_without_description",
        "active_kind_attack",
        "attack_with_mark_kind",
    }
    assert {case["name"] for case in valid} >= {"all_combat_fields", "legacy_no_combat_fields"}
    assert set(corpus["condition_names"]) == set(CONDITION_CATALOG)
    assert set(corpus["resistance_tags"]) == set(RESISTANCE_TAGS)
    assert len(corpus["condition_names"]) == len(CONDITION_CATALOG)
    assert len(corpus["resistance_tags"]) == len(RESISTANCE_TAGS)
    assert_corpus_floors(valid, invalid)
    derived = [case for case in valid if case.get("spec_derived")]
    assert {case["name"] for case in derived} >= {"spec_shadeling", "spec_hollowmoth", "spec_bandit"}
    assert {case["block"]["category"] for case in valid} == CATEGORIES
    catalog = json.loads(CATALOG.read_text())
    ids = {row["id"] for row in catalog}
    assert ids
    for case in valid:
        assert case["block"]["loot_table_id"] in ids
        assert validate_creature_stat_block(case["block"]) == [], case["name"]
    for case in invalid:
        assert case["expected"]
        if "field" in case:
            assert all(case["field"] in reason for reason in case["expected"]), case["name"]
        assert validate_creature_stat_block(case["block"]) == case["expected"], case["name"]


def test_hollow_exemplar_fixtures_match_catalog() -> None:
    exemplar_ids = {"hollow_shadeling", "hollow_hollowmoth"}
    corpus = json.loads(CORPUS.read_text())
    exemplars = [case for case in corpus["valid"] if case["block"]["id"] in exemplar_ids]
    assert len(exemplars) == 2
    assert {case["block"]["id"] for case in exemplars} == exemplar_ids
    catalog = {row["id"]: row for row in json.loads((ROOT / "content/creatures.json").read_text())}
    for case in exemplars:
        assert case["block"] == catalog[case["block"]["id"]]


def key_paths(node, prefix=()):
    items = node.items() if isinstance(node, dict) else enumerate(node[:1])
    for key, child in items:
        path = (*prefix, key)
        if isinstance(node, dict):
            yield path
        # audio.special keys are free-form, so none of them is required.
        if isinstance(child, (dict, list)) and path != ("audio", "special"):
            yield from key_paths(child, path)


def field_name(path):
    return "".join(f"[{part}]" if type(part) is int else f".{part}" for part in path).lstrip(".")


def test_every_spec_field_is_required():
    corpus = json.loads(CORPUS.read_text())
    checked = set()
    for case in corpus["valid"]:
        if not case.get("spec_derived"):
            continue
        for path in key_paths(case["block"]):
            block = copy.deepcopy(case["block"])
            parent = block
            for part in path[:-1]:
                parent = parent[part]
            del parent[path[-1]]
            name = field_name(path)
            assert validate_creature_stat_block(block) == [f"{name}: required"], case["name"]
            checked.add(name)
    assert {"reactions", "hollow.class", "attacks[0].damage", "actives[0].narration_cue"} <= checked
