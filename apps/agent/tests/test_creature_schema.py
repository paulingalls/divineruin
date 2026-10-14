import copy
import json
from pathlib import Path

import pytest

from conditions import CONDITION_CATALOG
from creature_schema import validate_creature_stat_block
from encounter_actions import ACTION_KINDS
from social_resolution import RESISTANCE_TAGS

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "packages/shared/fixtures/creature_blocks.json"
CATALOG = ROOT / "content/loot_tables.json"


def test_shared_creature_corpus():
    corpus = json.loads(CORPUS.read_text())
    valid, invalid = corpus["valid"], corpus["invalid"]
    assert set(corpus["action_kinds"]) == set(ACTION_KINDS)
    assert set(corpus["condition_names"]) == set(CONDITION_CATALOG)
    assert set(corpus["resistance_tags"]) == set(RESISTANCE_TAGS)
    assert len(corpus["condition_names"]) == len(CONDITION_CATALOG)
    assert len(corpus["resistance_tags"]) == len(RESISTANCE_TAGS)
    catalog = json.loads(CATALOG.read_text())
    ids = {row["id"] for row in catalog}
    for case in valid:
        assert case["block"]["loot_table_id"] in ids
        assert validate_creature_stat_block(case["block"]) == [], case["name"]
    for case in invalid:
        if "field" in case:
            assert all(case["field"] in reason for reason in case["expected"]), case["name"]
        assert validate_creature_stat_block(case["block"]) == case["expected"], case["name"]


def test_hollow_exemplar_fixtures_match_catalog() -> None:
    exemplar_ids = {"hollow_shadeling", "hollow_hollowmoth"}
    corpus = json.loads(CORPUS.read_text())
    exemplar_names = {"spec_shadeling", "spec_hollowmoth"}
    exemplars = [case for case in corpus["valid"] if case["name"] in exemplar_names]
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


@pytest.mark.parametrize("field,value", [("attack_source", "bad"), ("self_heal", "raw_damage")])
def test_catalog_runtime_extensions_use_creature_public_boundary(field, value):
    block = copy.deepcopy(json.loads(CORPUS.read_text())["valid"][0]["block"])
    attack = block["attacks"][0]
    attack.update(attack_source="catalog", self_heal="damage_dealt")
    assert validate_creature_stat_block(block) == []
    attack[field] = value
    assert any(field in problem for problem in validate_creature_stat_block(block))


def catalog():
    return json.loads((ROOT / "content/creatures.json").read_text())


@pytest.mark.parametrize(
    "sequence",
    [
        None,
        {},
        {"name": "", "attacks": ["Claw"]},
        {"name": "Claw", "attacks": ["Claw"]},
        {"name": "Multiattack", "attacks": []},
        {"name": "Multiattack", "attacks": ["unknown"]},
        {"name": "Multiattack", "attacks": [3]},
    ],
)
def test_python_rejects_invalid_catalog_sequence(sequence):
    row = copy.deepcopy(next(r for r in catalog() if r["id"] == "hollow_mawling"))
    row["multiattack_sequence"] = sequence
    assert validate_creature_stat_block(row)


@pytest.mark.parametrize("change", ["active_only", "ambiguous", "malformed", "name_collision"])
def test_python_rejects_unresolvable_sequence(change):
    row = copy.deepcopy(next(r for r in catalog() if r["id"] == "hollow_mawling"))
    if change == "active_only":
        row["multiattack_sequence"]["attacks"] = [row["actives"][1]["name"]]
    elif change == "ambiguous":
        row["attacks"].append({**row["attacks"][0], "name": "cLAW"})
    elif change == "malformed":
        row["multiattack_sequence"]["attacks"] = "Claw"
    else:
        row["multiattack_sequence"]["name"] = row["actives"][1]["name"]
    assert validate_creature_stat_block(row)


def test_authored_mawling_sequence_validates():
    mawling = next(r for r in catalog() if r["id"] == "hollow_mawling")
    assert validate_creature_stat_block(mawling) == []
    repeated = copy.deepcopy(mawling)
    repeated["multiattack_sequence"]["attacks"] = ["claw", "CLAW"]
    assert validate_creature_stat_block(repeated) == []


@pytest.mark.parametrize(
    "overrides,diagnostic",
    [
        ({"elite": ["claw", "CLAW"], "boss": ["Claw"]}, None),
        ({}, None),
        *[({role: ["Claw"]}, f".{role}: unknown role") for role in ("bogus", "minion", "standard", "named")],
        *[(value, ": expected object") for value in (None, [], "elite")],
        *[({"elite": value}, ".elite: expected array") for value in (None, "Claw")],
        ({"elite": []}, ".elite: expected non-empty array"),
        *[({"elite": [ref]}, ".elite: expected unambiguous attack reference") for ref in (3, "unknown", "Scatter")],
    ],
)
def test_role_sequence_schema(overrides, diagnostic):
    row = copy.deepcopy(next(r for r in catalog() if r["id"] == "hollow_mawling"))
    row["multiattack_sequence"]["attacks_by_role"] = overrides
    expected = [] if diagnostic is None else ["multiattack_sequence.attacks_by_role" + diagnostic]
    assert validate_creature_stat_block(row) == expected


def test_role_sequence_rejects_ambiguous_reference():
    row = copy.deepcopy(next(r for r in catalog() if r["id"] == "hollow_mawling"))
    row["multiattack_sequence"] = {
        "name": "Multiattack",
        "attacks": ["Dissolution Maw"],
        "attacks_by_role": {"elite": ["claw"]},
    }
    row["attacks"].append({**row["attacks"][0], "name": "cLAW"})
    assert validate_creature_stat_block(row) == [
        "multiattack_sequence.attacks_by_role.elite: expected unambiguous attack reference"
    ]
