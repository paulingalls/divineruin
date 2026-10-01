"""The story-138 composition has explicit, source-bound combat dispositions."""

import copy
import json
from collections import Counter
from pathlib import Path

import pytest

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
    ]
)
MARKER = "## Combat Effect Inventory"
GROUPS = ("attacks", "actives", "passives", "reactions", "multiattack", "signature_ability")

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
            if group in ("multiattack", "signature_ability"):
                entries = [row[group]] if row.get(group) else []
            else:
                entries = row[group]
            for entry in entries:
                name = entry if isinstance(entry, str) else entry["name"]
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
        if key[1] == "attacks":
            expected = {
                ("hollow_shadeling", "Corrosive Touch"): "mixed",
                ("hollow_mawling", "Dissolution Maw"): "mixed",
                ("hollow_mawling", "Lunge"): "mixed",
                ("hollow_knight", "Corrupted Blade"): "mixed",
                ("hollow_warden", "Absorb"): "scheduled",
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
        assert entry["status"] == "scheduled" and f"kind {kind};" in entry["effects"]
        assert "136" in entry["resolver"] and "137" in entry["resolver"]
    assert not any(key[1] == "reactions" for key in sources)


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
        for effect in REQUIRED_EFFECTS.get((entry["species"], entry["name"]), ()):
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
