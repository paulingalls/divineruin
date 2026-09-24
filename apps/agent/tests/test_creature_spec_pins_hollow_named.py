"""The three Named stat blocks, bestiary lines 440-608."""

import asyncio
import copy
import importlib
import json
import sys
from pathlib import Path

import pytest

from creature_schema import validate_creature_stat_block
from materials import parse_material_row

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
seed_content = importlib.import_module("seed_content")

SPEC = {
    "hollow_choir": ("The Choir", 16, 200, 18, 30, (1, 18, 18, 14, 20, 22), ("WIS", "CHA", "CON"), 3000, 600, 5),
    "hollow_still": ("The Still", 18, 250, 20, 0, (1, 1, 22, 16, 22, 24), ("CON", "WIS", "CHA"), 5000, 2980, 6),
    "hollow_architect": (
        "The Architect",
        20,
        300,
        19,
        40,
        (20, 14, 20, 22, 18, 16),
        ("INT", "CON", "WIS", "CHA"),
        5000,
        2640,
        8,
    ),
}
ATTACKS = {
    "hollow_choir": (
        ("Memory Scream", "area", 60, 0, "3d8", "psychic", "WIS save DC 18", "WIS", 18, "stunned"),
        ("Dissonant Chord", "ranged", 120, 10, "2d10+6", "psychic", "CON save DC 18", "CON", 18, None),
    ),
    "hollow_still": (
        ("Serenity's Touch", "melee", 5, 0, "2d6", "psychic", "Auto-hit (no roll)", "WIS", 20, None),
        ("Perfect Memory", "ranged", 120, 12, "3d8", "psychic", "WIS save DC 20", "WIS", 20, None),
    ),
    "hollow_architect": (
        ("Construct Slam", "melee", 15, 11, "3d10+5", "bludgeoning", "2d6 force", None, None, None),
        ("Geometry Strike", "ranged", 120, 10, "2d8+6", "force", "Auto-hit against targets touching", None, None, None),
    ),
}
ABILITIES = {
    "hollow_choir": (
        ("No Physical Form", "Aura of Lost Voices", "Memory Predator", "Resonance Core"),
        ("Stolen Melody", "Cacophony", "Silence Void"),
        ("Harmonic Shield",),
    ),
    "hollow_still": (
        ("Zone Entity", "Paradise Trap", "Gentle Absorption", "No Hostility"),
        ("Illusory Perfection", "Rejection", "Final Stillness"),
        (),
    ),
    "hollow_architect": (
        ("Architect's Domain", "Incorporeal Movement", "Legendary Resistance", "Alien Intelligence"),
        ("Reshape", "Entomb", "Cathedral", "Summon Constructs", "Shift Wall", "Geometry Strike"),
        ("Reactive Architecture",),
    ),
}
LOOT = {
    "hollow_choir": (
        ("choir_resonance_crystal", 1, 1.0, (("arcana", "expert"),)),
        ("named_fragment", 1, 1.0, (("crafting", "expert"),)),
        ("freed_memories", "1d6", 1.0, ()),
    ),
    "hollow_still": (("named_fragment", 1, 1.0, (("crafting", "expert"),)),),
    "hollow_architect": (
        ("architect_blueprint_fragment", "1d4", 1.0, (("arcana", "expert"),)),
        ("living_stone", "2d6", 1.0, (("crafting", "expert"),)),
        ("named_fragment", 1, 1.0, (("crafting", "expert"),)),
        ("void_touched_foundation", 1, 0.5, (("arcana", "expert"), ("crafting", "expert"))),
    ),
}
VULNERABILITIES = {
    "hollow_choir": ("radiant", "psychic", "silence_effects"),
    "hollow_still": ("radiant", "divine", "fire", "loud_sound"),
    "hollow_architect": ("radiant", "divine", "siege_weapons"),
}
RULES = {
    "hollow_choir": ("DC 15", "DC 18", "DC 20", "4d8 thunder", "3 rounds", "DC 16"),
    "hollow_still": ("Six hidden anchors", "40-45 HP", "DC 18", "24 continuous", "DC 22", "4+ anchors"),
    "hollow_architect": (
        "0.5 mile",
        "3/day",
        "20 ft × 20 ft",
        "3d8 bludgeoning",
        "4d10 force",
        "2d4 minions",
        "3/round",
        "Reshape costs 2 of 3/round",
    ),
}
RECHARGES = {
    "hollow_choir": ("5-6", "1/encounter", "1/encounter"),
    "hollow_still": ("1/round", "5-6", "1/encounter"),
    "hollow_architect": ("1/round", "5-6", "1/encounter", "1/encounter", None, None),
}


def catalog(name):
    return {row["id"]: row for row in json.loads((ROOT / "content" / name).read_text())}


def assert_loot(table, key):
    actual = tuple(
        (d["item_id"], d["quantity"], d["chance"], tuple((r["skill"], r["tier"]) for r in d["requires"]))
        for d in table["drops"]
    )
    assert actual == LOOT[key]


def assert_pin(row, key):
    name, level, hp, ac, speed, attributes, saves, xp, aura, resonance = SPEC[key]
    assert (row["name"], row["category"], row["tier"], row["level"], row["hp"], row["ac"], row["speed"]) == (
        name,
        "hollow",
        4,
        level,
        hp,
        ac,
        speed,
    )
    assert tuple(row["attributes"][stat] for stat in ("STR", "DEX", "CON", "INT", "WIS", "CHA")) == attributes
    assert tuple(row["save_proficiencies"]) == saves
    assert row["xp_reward"] == xp
    assert (row["hollow"]["class"], row["hollow"]["corruption_aura"], row["hollow"]["resonance_on_death"]) == (
        "named",
        aura,
        resonance,
    )
    assert row["hollow"]["veil_effect"].strip()
    assert tuple(row["hollow"]["vulnerable_to"]) == VULNERABILITIES[key]
    for group, expected in zip(("passives", "actives", "reactions"), ABILITIES[key], strict=True):
        assert tuple(a["name"] for a in row[group]) == expected
        assert all(a["description"] for a in row[group])
    assert tuple(a["recharge"] for a in row["actives"]) == RECHARGES[key]
    ability_text = " ".join(a["description"] for group in ("passives", "actives", "reactions") for a in row[group])
    assert all(rule in ability_text for rule in RULES[key])
    for field in ("first_sighting", "attack_cue", "wounded_cue", "death_cue", "ambient_cue"):
        assert row["narration"][field].strip()
    assert row["audio"]["ambient"].strip()
    assert row["behavior"]["tactics"].strip()
    assert validate_creature_stat_block(row) == []
    actual = row["attacks"]
    assert len(actual) == 2
    for attack, (*fields, rule, save, dc, condition) in zip(actual, ATTACKS[key], strict=True):
        assert (
            attack["name"],
            attack["type"],
            attack["reach"],
            attack["to_hit"],
            attack["damage"],
            attack["damage_type"],
        ) == tuple(fields)
        assert rule in attack["special"]
        assert (attack.get("save"), attack.get("dc"), attack.get("applies_condition")) == (save, dc, condition)
        assert "half_on_success" not in attack
    if key == "hollow_choir":
        assert "Deafened 1 minute" in actual[1]["special"]
    if key == "hollow_still":
        assert "Charmed for 1 hour" in actual[0]["special"]


def test_named_spec_stats_attacks_abilities_and_validator():
    creatures = catalog("creatures.json")
    for key in SPEC:
        assert_pin(creatures[key], key)


def test_named_loot_materials_and_seed():
    creatures, tables, materials = (
        catalog(name) for name in ("creatures.json", "loot_tables.json", "materials_catalog.json")
    )
    for key in LOOT:
        table = tables[creatures[key]["loot_table_id"]]
        assert table["hollow_residue"] is True
        assert seed_content.validate_loot_table(table) == []
        assert_loot(table, key)
        for drop in table["drops"]:
            parse_material_row(drop["item_id"], materials[drop["item_id"]])

    class Connection:
        def __init__(self):
            self.creatures = set()

        async def execute(self, query, key, data):
            if "INSERT INTO creatures" in query:
                self.creatures.add(key)

    conn = Connection()
    asyncio.run(seed_content.seed(conn))
    assert set(SPEC) <= conn.creatures


def test_named_pins_reject_changed_stat_attack_and_loot():
    row = catalog("creatures.json")["hollow_choir"]
    for mutate in (
        lambda x: x.__setitem__("hp", 201),
        lambda x: x["attacks"][0].__setitem__("reach", 61),
        lambda x: x["attacks"][0].__setitem__("dc", 17),
        lambda x: x["attacks"][0].pop("applies_condition"),
        lambda x: x["attacks"][1].__setitem__("applies_condition", "deafened"),
    ):
        changed = copy.deepcopy(row)
        mutate(changed)
        with pytest.raises(AssertionError):
            assert_pin(changed, "hollow_choir")
    table = catalog("loot_tables.json")["loot_hollow_choir"]
    for mutate in (
        lambda x: x["drops"][0].__setitem__("quantity", 2),
        lambda x: x["drops"][1]["requires"][0].__setitem__("tier", "trained"),
    ):
        changed = copy.deepcopy(table)
        mutate(changed)
        with pytest.raises(AssertionError):
            assert_loot(changed, "hollow_choir")
