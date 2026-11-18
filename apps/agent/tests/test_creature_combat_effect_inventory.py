import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def catalog():
    return json.loads((ROOT / "content/creatures.json").read_text())


def test_hollow_metadata_retains_only_unimplemented_claims():
    from creature_combat import translate_creature
    from creature_combat_effects import deferred_effects

    rows = catalog()
    hollows = [row for row in rows if row["hollow"] and row["hollow"]["class"] != "named"]
    assert hollows
    for row in hollows:
        translated = translate_creature(row, encounter_id="metadata", enemy_id=row["id"], role="standard")
        assert translated["hollow"] == {k: row["hollow"][k] for k in ("corruption_aura", "resonance_on_death")}
        source = next(e["source"] for e in translated["deferred_effects"] if e["group"] == "hollow")
        expected = {k: v for k, v in row["hollow"].items() if k not in translated["hollow"]}
        expected["vulnerable_to"] = [
            v for v in expected["vulnerable_to"] if v not in {"radiant", "fire", "psychic", "physical_damage"}
        ]
        assert source == expected
    named = [row for row in rows if row["hollow"] and row["hollow"]["class"] == "named"]
    assert named
    for row in named:
        expected = dict(row["hollow"])
        if row["id"] == "hollow_choir":
            for field in ("corruption_aura", "resonance_on_death"):
                expected.pop(field)
        expected["vulnerable_to"] = [
            v for v in expected["vulnerable_to"] if v not in {"radiant", "fire", "psychic", "physical_damage"}
        ]
        assert next(e["source"] for e in deferred_effects(row) if e["group"] == "hollow") == expected


@pytest.mark.parametrize("field", ["corruption_aura", "resonance_on_death"])
def test_negative_hollow_snapshot_is_refused(field):
    from creature_combat import translate_creature

    row = next(r for r in catalog() if r["id"] == "hollow_mawling")
    row["hollow"][field] = -1
    with pytest.raises(ValueError, match=field):
        translate_creature(row, encounter_id="snapshot", enemy_id="victim", role="standard")


def test_hollow_snapshot_is_independent_of_catalog_mutation():
    from creature_combat import translate_creature

    row = next(r for r in catalog() if r["id"] == "hollow_mawling")
    translated = translate_creature(row, encounter_id="snapshot", enemy_id="victim", role="standard")
    row["hollow"]["resonance_on_death"] = 9
    row["hollow"]["corruption_aura"] = 90
    assert translated["hollow"] == {"corruption_aura": 5, "resonance_on_death": 1}


def test_choir_metadata_retains_only_unimplemented_guidance():
    from creature_combat_effects import deferred_effects

    rows = json.loads((ROOT / "content/creatures.json").read_text())
    choir = next(row for row in rows if row["id"] == "hollow_choir")
    effects = deferred_effects(choir)
    names = {effect["name"] for effect in effects}
    assert names == {
        "Memory Predator",
        "Stolen Melody",
        "hollow",
    }
    melody = next(effect for effect in effects if effect["name"] == "Stolen Melody")
    assert melody["source"] == {"name": "Stolen Melody", "description": "The DM speaks in the stolen voice."}
    for name in {"Memory Predator"}:
        assert next(effect for effect in effects if effect["name"] == name)["source"] == next(
            source for source in choir["passives"] if source["name"] == name
        )

    hollow = next(effect for effect in effects if effect["name"] == "hollow")
    assert hollow["source"] == {
        key: value
        for key, value in choir["hollow"].items()
        if key not in {"corruption_aura", "resonance_on_death", "vulnerable_to"}
    } | {"vulnerable_to": ["silence_effects"]}


def test_executed_affinity_passives_leave_only_residual_guidance():
    from creature_combat_effects import deferred_effects

    executed = {
        ("corrupted_treant", "Vulnerability to Fire"),
        ("corrupted_treant", "Resistance"),
        ("dire_bear", "Thick Hide"),
        ("war_golem", "Damage Immunity"),
        ("deepstone_guardian", "Damage Immunity"),
        ("hollow_weaver", "Fragile Form"),
    }
    residual = {
        ("cave_wyrm", "Scales"): "Climbs 30 ft and burrows 10 ft.",
        ("tidecaller_eel", "Electricity Absorption"): "Heals HP equal to lightning damage dealt to it.",
        ("thunderbird", "Lightning Absorption"): "Heals equal to lightning damage dealt to it.",
    }
    for row in catalog():
        effects = {e["name"]: e["source"] for e in deferred_effects(row)}
        for cid, name in executed:
            if cid == row["id"]:
                assert name not in effects
        for (cid, name), description in residual.items():
            if cid == row["id"]:
                assert effects[name]["description"] == description
