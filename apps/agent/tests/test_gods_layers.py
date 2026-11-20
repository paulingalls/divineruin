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
    for patron_id, gift_id in (
        ("mortaen", "mortaen_deaths_awareness"),
        ("nythera", "nythera_horizon_sense"),
        ("orenthel", "orenthel_dawns_resilience"),
    ):
        gift = next(row["layer_1_gift"] for row in rows if row["god_id"] == patron_id)
        assert (gift["id"], gift["status"], gift["resolution"], gift["implementation_id"]) == (
            gift_id,
            "active",
            "engine",
            gift_id,
        )
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
    narrated = {
        "veythar_lorekeepers_library",
        "valdris_discern_lies",
        "syrath_whisper_network",
        "nythera_charted_course",
        "mortaen_speak_with_dead",
        "zhael_prophecy_fragment",
        "syrath_the_veilwatchers_eye",
    }
    abilities = [a for row in rows for a in row["layer_3_tier_abilities"].values()]
    assert len(abilities) == len({a["id"] for a in abilities}) == 30
    assert {a["id"] for a in abilities if (a["status"], a["resolution"]) == ("active", "narrated")} == narrated
    passives = {"veythar_scholars_ward", "kaelen_warriors_endurance", "orenthel_beacon"}
    battle_cry = "kaelen_battle_cry_of_the_ironhand"
    judgment = "kaelen_kaelens_judgment"
    surge = "orenthel_restoration_surge"
    devoted = next(row["layer_3_tier_abilities"]["devoted"] for row in rows if row["god_id"] == "orenthel")
    assert tuple(devoted[key] for key in ("id", "status", "resolution", "implementation_id", "recharge")) == (
        surge,
        "active",
        "engine",
        surge,
        "long_rest",
    )
    mark = "valdris_mark_of_justice"
    valdris = next(row["layer_3_tier_abilities"]["devoted"] for row in rows if row["god_id"] == "valdris")
    assert (
        valdris["id"],
        valdris["status"],
        valdris["resolution"],
        valdris.get("implementation_id"),
        valdris["recharge"],
    ) == (mark, "active", "engine", mark, "long_rest")
    veilstep_id = "syrath_veilstep"
    veilstep = next(row["layer_3_tier_abilities"]["devoted"] for row in rows if row["god_id"] == "syrath")
    assert (
        veilstep["id"],
        veilstep["status"],
        veilstep["resolution"],
        veilstep.get("implementation_id"),
        veilstep["recharge"],
    ) == (veilstep_id, "active", "engine", veilstep_id, "long_rest")
    engine = {"zhael_lucky", battle_cry, judgment, surge, mark, veilstep_id, *passives}
    assert {a["id"] for a in abilities if (a["status"], a["resolution"]) == ("active", "engine")} == engine
    pending = [a for a in abilities if a["id"] not in narrated | engine]
    assert len(pending) == 14
    for ability in abilities:
        if ability["id"] in passives:
            assert (ability["recharge"], ability["implementation_id"]) == ("always", ability["id"])
    cry = next(a for a in abilities if a["id"] == battle_cry)
    assert (cry["recharge"], cry["implementation_id"]) == ("long_rest", battle_cry)
    worthy_foe = next(a for a in abilities if a["id"] == judgment)
    assert (worthy_foe["recharge"], worthy_foe["implementation_id"]) == ("per_session", judgment)
    assert all((a["status"], a["resolution"]) == ("pending", "engine") for a in pending)
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
    assert f"{case['patron']}.{case['field']}:" in str(error.value)


@pytest.mark.parametrize("shape", [None, {}, [], [None]])
def test_invalid_catalog_shape(shape, read_catalog):
    with pytest.raises(ValueError, match=r"gods|god_id"):
        read_catalog(shape)


@pytest.mark.parametrize(
    "defect", ["duplicate_patron", "duplicate_ability", "cross_catalog_ability", "missing_id", "blank_id", "numeric_id"]
)
def test_invalid_catalog_identity(defect, read_catalog):
    rows = copy.deepcopy(CATALOG)
    if defect == "duplicate_patron":
        rows.append(copy.deepcopy(rows[0]))
        field = "veythar.god_id"
    elif defect == "duplicate_ability":
        tiers = rows[0]["layer_3_tier_abilities"]
        tiers["devoted"]["id"] = tiers["acknowledged"]["id"]
        field = "veythar.layer_3_tier_abilities.devoted.id"
    elif defect == "cross_catalog_ability":
        rows[0] = copy.deepcopy(CORPUS["valid"][0]["profile"])
        rows[1] = copy.deepcopy(rows[0])
        rows[1]["god_id"] = "veythar_fixture"
        field = "veythar_fixture.layer_3_tier_abilities.acknowledged.id"
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


@pytest.mark.parametrize("case", CORPUS["layer_1_cases"], ids=lambda c: c["id"])
def test_layer_1_profile_reaches_loader(case, read_catalog):
    profile = copy.deepcopy(CORPUS["valid"][0]["profile"])
    gift = profile["layer_1_gift"]
    gift.update(case.get("set", {}))
    if "delete" in case:
        del gift[case["delete"]]
    rows = with_profile(profile)
    if "field" in case:
        with pytest.raises(ValueError, match=re.escape("veythar.layer_1_gift." + case["field"] + ":")):
            read_catalog(rows)
    else:
        assert read_catalog(rows) == rows
