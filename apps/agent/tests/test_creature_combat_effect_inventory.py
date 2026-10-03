"""The story-138 composition has explicit, source-bound combat dispositions."""

import copy
import json
from collections import Counter
from pathlib import Path

import pytest
from choir_effect_inventory_helpers import CHOIR, assert_choir_disposition, assert_choir_table

ROOT = Path(__file__).resolve().parents[3]
IDS = set(
    [
        "hollow_shadeling",
        "hollow_wisp",
        "hollow_mawling",
        "hollowed_scout",
        "bandit",
        "bandit_captain",
        "ashmark_soldier",
        "ashmark_sergeant",
        "hollow_warden",
        "cultist",
        "cult_fanatic",
        "cult_leader",
        "hollow_knight",
        "hollow_choir",
    ]
)
MARKER = "## Combat Effect Inventory"
GROUPS = ("attacks", "actives", "passives", "reactions", "multiattack", "signature_ability", "hollow")

REQUIRED_EFFECTS = {
    ("hollow_shadeling", "Corrosive Touch"): ("organic material", "double damage"),
    ("hollow_shadeling", "Amorphous"): ("1 inch", "grapple/restraint immunity"),
    ("hollow_shadeling", "Corruption Trail"): ("surface damage1", "visible marks"),
    ("hollow_shadeling", "Sunlight Sensitivity"): ("disadvantage", "minus2"),
    ("hollow_mawling", "Dissolution Maw"): ("CON DC13", "durability 1d4"),
    ("hollow_mawling", "Lunge"): ("grapple", "advantage", "recharge"),
    ("hollow_mawling", "Scatter"): ("3+", "15 ft", "no reactions", "flank"),
    ("hollow_mawling", "Unsettling Silence"): ("No vocalization", "Stealth advantage"),
    ("hollow_mawling", "Dissolution Field"): ("Start turn grappled", "1d6"),
    ("hollow_mawling", "Adaptive Learning"): ("twice", "save/AC advantage", "encounter"),
    ("bandit", "Dirty Fighting"): ("blinded", "DEX DC12", "duration1", "encounter uses1"),
    ("bandit_captain", "Rally"): ("kind healing", "allied_bandits", "healing1d8", "encounter uses1"),
    ("bandit_captain", "Dirty Fighting"): ("prepare_attack", "next attack advantage", "on_hit blinded duration1"),
    ("bandit_captain", "Leadership Aura"): ("within30 ft", "attack plus1"),
    ("bandit_captain", "Cunning Action"): ("Bonus action", "Dash/Disengage/Hide"),
    ("hollow_warden", "Absorb"): ("actual damage dealt self-healing",),
    ("hollow_knight", "Corrupted Blade"): ("extra1d6", "crit CON DC14", "Stage1 Hollowed"),
    ("hollow_knight", "Shield Slam"): ("Damage", "STR DC14 prone"),
    ("hollow_knight", "Command Lesser"): ("up to4 Drift/Rend", "within60 ft", "bonus action"),
    ("hollow_knight", "Dissolution Strike"): ("extra3d6", "ignore resistance", "on-hit5 ft", "1 minute"),
    ("hollow_knight", "Unholy Fortitude"): ("At0 HP", "CON DC10", "to1 HP", "escalates5"),
    ("hollow_knight", "Remnant Tactics"): ("Dodge outnumbered", "terrain advantage"),
    ("hollow_knight", "Corrupted Resilience"): ("nonmagical slashing/piercing/bludgeoning", "magic full damage"),
    ("hollow_knight", "Fragment Voice"): (
        "former-ally",
        "WIS DC12 Shaken",
        "next attack disadvantage",
        "later cosmetic",
    ),
}


def inventory():
    text = (ROOT / "docs/game_mechanics/game_mechanics_bestiary.md").read_text()
    assert_choir_table(text)
    assert text.count(MARKER) == 1
    section = text.split(MARKER)[1].split("\n## ")[0]
    entries = []
    for line in section.splitlines():
        if line.startswith("| ") and not line.startswith("| Species "):
            fields = [field.strip().replace("&#124;", "|") for field in line.strip("|").split("|")]
            assert len(fields) == 9, line
            species, group, name, source, status, effects, resolver, deferred, duplicate = fields
            entries.append(
                dict(
                    species=species,
                    group=group,
                    name=name,
                    source=json.loads(source),
                    status=status,
                    effects=effects,
                    resolver=resolver,
                    deferred=deferred,
                    duplicate=duplicate,
                )
            )
    assert entries
    return entries


def source_entries(rows):
    assert rows
    assert Counter(row["id"] for row in rows if row["id"] in IDS) == Counter({key: 1 for key in IDS})
    sources = {}
    for row in rows:
        if row["id"] not in IDS:
            continue
        assert "action_pool" not in row
        for group in GROUPS:
            if group == "hollow" and row["id"] != "hollow_choir":
                continue
            if group in ("multiattack", "signature_ability", "hollow"):
                entries = [row[group]] if row.get(group) else []
            else:
                entries = row[group]
            for entry in entries:
                name = group if group == "hollow" else entry if isinstance(entry, str) else entry["name"]
                key = (row["id"], group, name)
                assert key not in sources
                sources[key] = entry
    assert sources
    return sources


def assert_effect_inventory(rows, entries):
    sources = source_entries(rows)
    assert entries
    declared = {(e["species"], e["group"], e["name"]): e for e in entries}
    assert len(declared) == len(entries)
    assert set(declared) == set(sources)
    for key, source in sources.items():
        entry = declared[key]
        assert entry["source"] == source, key
        if key[0] == "hollow_choir":
            assert_choir_disposition(key, entry)
            continue
        if key[1] == "attacks":
            expected = {
                ("hollow_shadeling", "Corrosive Touch"): "mixed",
                ("hollow_mawling", "Dissolution Maw"): "mixed",
                ("hollow_mawling", "Lunge"): "mixed",
                ("hollow_knight", "Corrupted Blade"): "mixed",
                ("hollow_warden", "Absorb"): "executable",
            }.get((key[0], key[2]), "executable")
            assert entry["status"] == expected, key
        elif key[1] in {"passives", "multiattack", "signature_ability"}:
            assert entry["status"] == ("narrative" if key[1] == "signature_ability" else "deferred"), key
        if entry["status"] in {"executable", "mixed"}:
            assert any(
                binding in entry["resolver"]
                for binding in (
                    "check_resolution_attack.resolve_attack",
                    "combat_enemy_action._resolve_enemy_condition_packet",
                    "combat_enemy_action.resolve_combined_attack_action",
                    "combat_marks.resolve_mark_action",
                    "combat_enemy_active.resolve_active",
                )
            ), key
        for effect in REQUIRED_EFFECTS.get((key[0], key[2]), ()):
            assert effect in entry["effects"], (key, effect)
        assert entry["effects"] and entry["resolver"] and entry["deferred"], key
        assert entry["status"] in {"executable", "mixed", "scheduled", "deferred", "duplicate", "narrative"}
        if entry["status"] in {"scheduled", "mixed"}:
            assert "136" in entry["resolver"] or "137" in entry["resolver"] or entry["deferred"] != "none", key
        if entry["status"] in {"deferred", "narrative"}:
            assert entry["deferred"] != "none", key
        if entry["status"] == "duplicate":
            assert entry["duplicate"] != "none"
            target = (key[0], *entry["duplicate"].split("/", 1))
            assert target in declared and declared[target]["status"] != "duplicate"
        else:
            assert entry["duplicate"] == "none"
    lunge = declared[("hollow_mawling", "actives", "Lunge")]
    assert lunge["status"] == "duplicate" and lunge["duplicate"] == "attacks/Lunge"
    for name, kind in (("Rally", "healing"), ("Dirty Fighting", "prepare_attack")):
        entry = declared[("bandit_captain", "actives", name)]
        assert (
            entry["status"] == ("mixed" if kind == "healing" else "executable") and f"kind {kind};" in entry["effects"]
        )
        assert "combat_enemy_active.resolve_active" in entry["resolver"]
    assert {(key[0], key[2]) for key in sources if key[1] == "reactions"} == {("hollow_choir", "Harmonic Shield")}


def catalog():
    return json.loads((ROOT / "content/creatures.json").read_text())


def test_effect_inventory():
    assert_effect_inventory(catalog(), inventory())


@pytest.mark.parametrize("group", GROUPS)
def test_effect_inventory_missing_lane(group):
    entries = inventory()
    removed = [e for e in entries if e["group"] != group]
    if group == "reactions":
        rows = catalog()
        next(r for r in rows if r["id"] == "bandit")[group].append({"name": "New reaction"})
    else:
        rows = catalog()
        assert removed != entries
    with pytest.raises(AssertionError):
        assert_effect_inventory(rows, removed)


def test_effect_inventory_every_entry_is_required():
    entries = inventory()
    for entry in entries:
        with pytest.raises(AssertionError):
            assert_effect_inventory(catalog(), [e for e in entries if e is not entry])


@pytest.mark.parametrize("group", ["attacks", "actives", "passives", "reactions"])
def test_effect_inventory_new_entry_and_changed_source(group):
    rows = catalog()
    row = next(r for r in rows if r["id"] == "hollow_mawling")
    row[group].append({"name": "Undeclared"})
    with pytest.raises(AssertionError):
        assert_effect_inventory(rows, inventory())
    if group in ("attacks", "passives"):
        rows = catalog()
        row = next(r for r in rows if r["id"] == "hollow_mawling")
        field = "special" if group == "attacks" else "description"
        row[group][0][field] += " Target is also blinded."
        with pytest.raises(AssertionError):
            assert_effect_inventory(rows, inventory())


def test_effect_inventory_dispositions_cannot_claim_false_execution():
    for species, group, name, field, value in [
        ("hollow_mawling", "actives", "Lunge", "status", "executable"),
        ("bandit_captain", "actives", "Rally", "effects", "command buff/healing"),
        ("bandit_captain", "actives", "Dirty Fighting", "resolver", "combat_marks.resolve_mark_action"),
    ]:
        entries = inventory()
        next(e for e in entries if (e["species"], e["group"], e["name"]) == (species, group, name))[field] = value
        with pytest.raises(AssertionError):
            assert_effect_inventory(catalog(), entries)
    with pytest.raises(AssertionError):
        assert_effect_inventory([], inventory())
    with pytest.raises(AssertionError):
        assert_effect_inventory(catalog(), [])
    for key in IDS:
        with pytest.raises(AssertionError):
            assert_effect_inventory([r for r in catalog() if r["id"] != key], inventory())
    for entry in inventory():
        for field in ("resolver", "effects", "deferred"):
            entries = copy.deepcopy(inventory())
            next(
                e
                for e in entries
                if e["species"] == entry["species"] and e["group"] == entry["group"] and e["name"] == entry["name"]
            )[field] = ""
            with pytest.raises(AssertionError):
                assert_effect_inventory(catalog(), entries)


def test_public_validator_absence_walk():
    from creature_public_validator_walk import assert_public_validator_walk, source_files

    assert_public_validator_walk(source_files(ROOT))


def test_public_validator_walk_faults_are_reachable(tmp_path):
    from creature_public_validator_walk import (
        assert_corpora,
        assert_public_python,
        assert_public_typescript,
        lane,
        source_files,
    )

    files = source_files(ROOT)
    lanes = assert_corpora(files)
    for key, paths in lanes.items():
        path = paths[0]
        if key[1] == "py":
            for defect in (
                "from combat_init_validation import _validate_enemy_action_shapes as renamed",
                "import combat_init_validation as module\nmodule._validate_enemy_resistance_tags([])",
                "from combat_init_validation import *",
                "import combat_init._validate_enemy_action_shapes as renamed",
            ):
                with pytest.raises(AssertionError):
                    assert_public_python(defect, path)
        else:
            with pytest.raises(AssertionError):
                assert_public_typescript([(str(path), "module._validate_enemy_action_shapes([])")])
        with pytest.raises(AssertionError):
            assert_corpora([p for p in files if lane(p) != key])
    with pytest.raises(AssertionError):
        assert_corpora([])
    with pytest.raises(AssertionError):
        assert_corpora(files, tmp_path)
    with pytest.raises(AssertionError):
        assert_corpora([*files, ROOT / "new_root" / "file.py"])


def test_effect_inventory_subeffects_and_real_resolvers():
    import importlib

    for binding in (
        "combat_packet._resolve_one_packet",
        "check_resolution_attack.resolve_attack",
        "combat_enemy_action._resolve_enemy_condition_packet",
        "combat_enemy_action.resolve_combined_attack_action",
        "combat_marks.resolve_mark_action",
        "combat_phase._boss_legendaries",
    ):
        module, name = binding.split(".")
        assert callable(getattr(importlib.import_module(module), name))
    for entry in inventory():
        effects = (
            CHOIR[(entry["group"], entry["name"])][1]
            if entry["species"] == "hollow_choir"
            else REQUIRED_EFFECTS.get((entry["species"], entry["name"]), ())
        )
        for effect in effects:
            entries = inventory()
            changed = next(
                e
                for e in entries
                if (e["species"], e["group"], e["name"]) == (entry["species"], entry["group"], entry["name"])
            )
            changed["effects"] = changed["effects"].replace(effect, "")
            with pytest.raises(AssertionError):
                assert_effect_inventory(catalog(), entries)


def test_public_validator_walk_excludes_detected_virtualenvs(tmp_path):
    from creature_public_validator_walk import source_files

    vendor = tmp_path / "scripts/audio/.venv-sa3"
    source = tmp_path / "scripts/audio/.local-source/validator.py"
    source.parent.mkdir(parents=True)
    source.write_text("validator = True\n")
    vendor.mkdir(parents=True)
    (vendor / "pyvenv.cfg").write_text("home = /test/python\n")
    installed = vendor / "lib/site-packages/vendor/tests/test_validator.py"
    installed.parent.mkdir(parents=True)
    installed.write_text("_validate_enemy_action_shapes = True\n")
    assert source_files(tmp_path) == [source]
    (vendor / "pyvenv.cfg").unlink()
    assert set(source_files(tmp_path)) == {source, installed}


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
        assert source == {k: v for k, v in row["hollow"].items() if k not in translated["hollow"]}
    named = [row for row in rows if row["hollow"] and row["hollow"]["class"] == "named"]
    assert named
    for row in named:
        expected = dict(row["hollow"])
        if row["id"] == "hollow_choir":
            for field in ("corruption_aura", "resonance_on_death"):
                expected.pop(field)
            expected.pop("vulnerable_to")
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
    }


def test_choir_dispositions_reject_fabricated_execution_and_changed_bindings():
    for entry in inventory():
        if entry["species"] != "hollow_choir":
            continue
        for field, value in (
            ("status", "deferred" if entry["status"] == "executable" else "executable"),
            ("deferred", "fabricated"),
            ("resolver", "fabricated"),
        ):
            changed = copy.deepcopy(inventory())
            next(
                e
                for e in changed
                if e["species"] == entry["species"] and e["group"] == entry["group"] and e["name"] == entry["name"]
            )[field] = value
            if field == "resolver" and entry["status"] == "narrative":
                continue
            with pytest.raises(AssertionError):
                assert_effect_inventory(catalog(), changed)


@pytest.mark.parametrize("binding", sorted({binding for _, _, bindings, _ in CHOIR.values() for binding in bindings}))
def test_choir_inventory_rejects_noncallable_resolver(binding, monkeypatch):
    import importlib

    module, name = binding.rsplit(".", 1)
    monkeypatch.setattr(importlib.import_module(module), name, None)
    with pytest.raises(AssertionError, match=binding):
        assert_effect_inventory(catalog(), inventory())


def test_choir_inventory_rejects_a_blank_line_table_break():
    text = (ROOT / "docs/game_mechanics/game_mechanics_bestiary.md").read_text()
    broken = text.replace(
        "\n| hollow_choir | attacks | Memory Scream", "\n\n| hollow_choir | attacks | Memory Scream", 1
    )
    with pytest.raises(AssertionError, match="continue the Markdown table"):
        assert_choir_table(broken)
