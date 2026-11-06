import copy
import json
import re
from pathlib import Path

import pytest

import _gods_content
from _gods_content import load_gods

ROOT = Path(__file__).resolve().parents[3]
CORPUS = json.loads((ROOT / "packages/shared/fixtures/god_profiles.json").read_text())
CATALOG = json.loads((ROOT / "content/gods.json").read_text())
TIERS = {"acknowledged", "devoted", "exalted"}
EXPECTED_MODIFIERS = {
    "veythar": [("flickering_damage_dice", "arcane_flickering", 2)],
    "kaelen": [("generation_delta", "combat_aid", -1)],
    "aelora": [("ward_penalty_immunity", "inside_active_veil_ward", True)],
    "thyra": [("primal_multiplier_steps", "primal_on_natural_ground", -1), ("generation_delta", "natural_ground", -1)],
    "syrath": [("generation_delta", "hidden_or_stealthed", -2)],
    "orenthel": [("generation_override", "healing", 0)],
    "valdris": [("generation_multiplier", "wrongdoer_target", 0.5)],
    "mortaen": [("generation_override", "target_at_zero_hp", 0)],
    "nythera": [("generation_delta", "unvisited_location", -1)],
    "zhael": [("echo_roll_choice", "overreach", 2)],
}


def test_authored_layers_match_mechanics():
    rows = load_gods()
    assert len(rows) == len(CORPUS["patron_ids"]) == 10
    doc = (ROOT / "docs/game_mechanics/game_mechanics_patrons.md").read_text()
    sections = {}
    for section in doc.split("### ")[1:]:
        patron = section.split(",", 1)[0].lower()
        if patron in CORPUS["patron_ids"]:
            sections[patron] = dict(
                (tier.lower(), name.strip())
                for tier, name in re.findall(r"^\| (Acknowledged|Devoted|Exalted) \| ([^|]+) \|", section, re.M)
            )
    assert len(sections) == 10
    assert sum(len(tiers) for tiers in sections.values()) == 30
    for row in rows:
        patron = row["god_id"]
        layer = row["layer_2_resonance"]
        assert layer is not None, patron
        assert [(m["kind"], m["applies_to"], m["value"]) for m in layer["modifiers"]] == EXPECTED_MODIFIERS[patron]
        abilities = row["layer_3_tier_abilities"]
        assert set(abilities) == TIERS
        assert {t: a["name"] for t, a in abilities.items()} == sections[patron]


@pytest.fixture
def read_catalog(tmp_path, monkeypatch):
    path = tmp_path / "gods.json"
    monkeypatch.setattr(_gods_content, "_GODS_JSON_PATH", path)

    def read(rows):
        path.write_text(json.dumps(rows))
        load_gods.cache_clear()
        return load_gods()

    yield read
    load_gods.cache_clear()


def with_profile(profile):
    rows = copy.deepcopy(CATALOG)
    rows[0] = copy.deepcopy(profile)
    return rows


def valid_cases():
    cases = list(CORPUS["valid"])
    generated = []
    for kind, spec in CORPUS["vocabulary"].items():
        for predicate in spec["predicates"]:
            profile = copy.deepcopy(cases[0]["profile"])
            profile["layer_2_resonance"]["modifiers"] = [dict(kind=kind, applies_to=predicate, value=spec["sample"])]
            generated.append(dict(id=f"{kind}/{predicate}", profile=profile))
    assert cases and generated and CORPUS["invalid"]
    return cases + generated


@pytest.mark.parametrize("case", valid_cases(), ids=lambda c: c["id"])
def test_valid_profiles_reach_loader(case, read_catalog):
    rows = with_profile(case["profile"])
    assert read_catalog(rows) == rows


@pytest.mark.parametrize("case", CORPUS["invalid"], ids=lambda c: c["id"])
def test_invalid_profiles_reach_loader(case, read_catalog):
    with pytest.raises(ValueError) as error:
        read_catalog(with_profile(case["profile"]))
    assert case["patron"] in str(error.value)
    assert case["field"] in str(error.value)


@pytest.mark.parametrize("shape", [None, {}, [], [None]])
def test_invalid_catalog_shape(shape, read_catalog):
    with pytest.raises(ValueError, match=r"gods|god_id"):
        read_catalog(shape)


@pytest.mark.parametrize("defect", ["duplicate_patron", "duplicate_ability", "missing_id", "blank_id", "numeric_id"])
def test_invalid_catalog_identity(defect, read_catalog):
    rows = copy.deepcopy(CATALOG)
    if defect == "duplicate_patron":
        rows.append(copy.deepcopy(rows[0]))
        field = "veythar.god_id"
    elif defect == "duplicate_ability":
        tiers = rows[0]["layer_3_tier_abilities"]
        tiers["devoted"]["id"] = tiers["acknowledged"]["id"]
        field = "veythar.layer_3_tier_abilities.devoted.id"
    else:
        rows[0]["god_id"] = {"missing_id": None, "blank_id": " ", "numeric_id": 2}[defect]
        if defect == "missing_id":
            del rows[0]["god_id"]
        field = "gods[0].god_id"
    with pytest.raises(ValueError, match=re.escape(field)):
        read_catalog(rows)


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_nonfinite_runtime_values(value, read_catalog):
    profile = copy.deepcopy(CORPUS["valid"][0]["profile"])
    profile["layer_2_resonance"]["modifiers"][0]["value"] = value
    with pytest.raises(ValueError, match=r"veythar.layer_2_resonance.modifiers\[0\].value"):
        read_catalog(with_profile(profile))
