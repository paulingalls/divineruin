"""Pins for the four Rend and Wrack catalog entries in the bestiary spec."""

import asyncio
import importlib
import json
import sys
from pathlib import Path

from creature_schema import validate_creature_stat_block
from materials import parse_material_row

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
seed_content = importlib.import_module("seed_content")

SPEC = {
    "hollow_mawling": ("Mawling", 2, 4, 38, 13, 35, 100, (14, 15, 13, 3, 10, 1), ("DEX", "CON"), "rend", 5, 1),
    "hollow_weaver": ("Hollow Weaver", 2, 5, 28, 11, 10, 150, (6, 8, 14, 6, 14, 1), ("CON", "WIS"), "rend", 30, 1),
    "hollow_knight": (
        "Hollowed Knight",
        3,
        8,
        85,
        16,
        30,
        450,
        (18, 12, 16, 8, 10, 6),
        ("STR", "CON", "WIS"),
        "wrack",
        10,
        2,
    ),
    "hollow_veilrender": ("Veilrender", 3, 10, 120, 14, 10, 700, (22, 4, 20, 3, 12, 1), ("STR", "CON"), "wrack", 60, 3),
}
ATTACKS = {
    "hollow_mawling": (
        ("Claw", "melee", 10, 5, "1d8+2", "slashing"),
        ("Dissolution Maw", "melee", 5, 5, "2d6+2", "necrotic"),
        ("Lunge", "melee", 10, 5, "1d8+2", "slashing"),
    ),
    "hollow_weaver": (("Spatial Lash", "melee", 15, 4, "1d6+2", "force"),),
    "hollow_knight": (
        ("Corrupted Blade", "melee", 5, 7, "1d10+4", "slashing"),
        ("Shield Slam", "melee", 5, 7, "1d6+4", "bludgeoning"),
    ),
    "hollow_veilrender": (
        ("Crushing Mass", "melee", 10, 8, "3d8+6", "bludgeoning"),
        ("Corruption Wave", "area", 30, 0, "2d8", "necrotic"),
    ),
}
ABILITIES = {
    "hollow_mawling": (("Unsettling Silence", "Dissolution Field", "Adaptive Learning"), ("Lunge", "Scatter"), ()),
    "hollow_weaver": (("Spatial Distortion", "Anchored", "Fragile Form"), ("Rearrange", "Spatial Fold"), ()),
    "hollow_knight": (
        ("Remnant Tactics", "Corrupted Resilience", "Fragment Voice"),
        ("Command Lesser", "Dissolution Strike", "Unholy Fortitude"),
        (),
    ),
    "hollow_veilrender": (
        ("Corruption Field", "Regeneration", "Siege Monster", "Massive"),
        ("Reality Crush", "Corruption Pulse"),
        ("Absorb Magic",),
    ),
}
VULNERABLE = {
    "hollow_mawling": ("radiant", "blessed_weapons", "divine_spells"),
    "hollow_weaver": ("physical_damage",),
    "hollow_knight": ("radiant", "blessed_weapons", "divine_spells", "turn_undead_hollow"),
    "hollow_veilrender": ("radiant", "divine_intervention", "veil_ward_artifacts"),
}
VEIL = {
    "hollow_mawling": "Natural sounds distort within 15 ft. Footsteps echo wrong. Combat sounds arrive delayed.",
    "hollow_weaver": "Reverb changes: small rooms echo like cathedrals, large spaces go acoustically dead, and footsteps sound wrong.",
    "hollow_knight": "Within 30 ft temperature drops, shadows fall wrong, and sounds of the former person’s life sometimes echo.",
    "hollow_veilrender": "Sound travels wrongly within 60 ft. Voices seem distant or muffled; acoustic space is rewritten.",
}
RULES = {
    "hollow_mawling": ("1d4 durability", "1d6 necrotic", "same tactic", "STR DC 13", "3+ mawlings"),
    "hollow_weaver": (
        "30 ft radius",
        "costs double",
        "physical damage",
        "different real location",
        "WIS save DC 13",
        "2d6 force",
    ),
    "hollow_knight": (
        "Stage 1 Hollowed",
        "Dodge",
        "non-magical",
        "WIS save DC 12",
        "up to 4",
        "3d6 necrotic",
        "DC increases by 5",
    ),
    "hollow_veilrender": (
        "double damage",
        "1d4 necrotic",
        "10 HP",
        "smaller than Huge",
        "4d8 force",
        "3d6 necrotic",
        "Focus cost × 3",
    ),
}
LOOT = {
    "hollow_mawling": (
        "loot_hollow_mawling",
        (
            ("rend_shard", 1, 0.75, (("crafting", "expert"),)),
            ("dissolution_membrane", 1, 0.25, (("crafting", "expert"), ("arcana", "trained"))),
        ),
    ),
    "hollow_weaver": (
        "loot_hollow_weaver",
        (
            ("spatial_residue", 1, 1.0, (("crafting", "expert"),)),
            ("woven_void_fragment", 1, 0.25, (("arcana", "expert"),)),
        ),
    ),
    "hollow_knight": (
        "loot_hollowed_knight_catalog",
        (
            ("corrupted_armor_fragments", "1d4", 1.0, ()),
            ("wrack_core", 1, 0.5, (("crafting", "expert"),)),
            ("remnant_identity", 1, 0.25, (("arcana", "trained"),)),
            ("salvageable_weapon", 1, 0.75, ()),
        ),
    ),
    "hollow_veilrender": (
        "loot_veilrender",
        (
            ("veilrender_carapace", "2d4", 1.0, ()),
            ("corruption_saturated_stone", "1d6", 1.0, ()),
            ("wrack_core_large", 1, 0.75, (("crafting", "expert"),)),
            ("veil_shard", 1, 0.25, (("arcana", "expert"),)),
        ),
    ),
}


def rows(name):
    return json.loads((ROOT / "content" / name).read_text())


def test_spec_stats_hollow_and_attacks():
    creatures = rows("creatures.json")
    assert len(creatures) >= 4
    for key, expected in SPEC.items():
        matches = [row for row in creatures if row["id"] == key]
        assert len(matches) == 1, key
        row = matches[0]
        assert row["category"] == "hollow"
        assert (
            row["name"],
            row["tier"],
            row["level"],
            row["hp"],
            row["ac"],
            row["speed"],
            row["xp_reward"],
            tuple(row["attributes"][a] for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")),
            tuple(row["save_proficiencies"]),
            row["hollow"]["class"],
            row["hollow"]["corruption_aura"],
            row["hollow"]["resonance_on_death"],
        ) == expected
        assert (
            tuple(
                (a["name"], a["type"], a["reach"], a["to_hit"], a["damage"], a["damage_type"]) for a in row["attacks"]
            )
            == ATTACKS[key]
        )
        assert (
            tuple(tuple(a["name"] for a in row[group]) for group in ("passives", "actives", "reactions"))
            == ABILITIES[key]
        )
        assert tuple(row["hollow"]["vulnerable_to"]) == VULNERABLE[key]
        assert row["hollow"]["veil_effect"] == VEIL[key]
        rules = (
            " ".join(a["special"] or "" for a in row["attacks"])
            + " "
            + " ".join(a["description"] for group in ("passives", "actives", "reactions") for a in row[group])
        )
        assert all(fragment in rules for fragment in RULES[key]), key
        assert validate_creature_stat_block(row) == []


def test_spec_mechanics():
    creatures = {row["id"]: row for row in rows("creatures.json")}
    mawling = creatures["hollow_mawling"]
    assert mawling["multiattack"] == "2 attacks — one Claw and one Dissolution Maw"
    assert mawling["attacks"][2]["properties"] == ["grapple"]
    assert mawling["attacks"][2]["escape_dc"] == 13
    assert "Recharge 5-6" in mawling["attacks"][2]["special"]
    assert "15 ft" in mawling["attacks"][2]["special"]
    knight = creatures["hollow_knight"]
    assert knight["multiattack"] == "2 attacks with Corrupted Blade"
    assert knight["actives"][0]["kind"] == "command"
    assert "1d6 necrotic" in knight["attacks"][0]["special"]
    assert {k: knight["attacks"][1][k] for k in ("applies_condition", "save", "dc")} == {
        "applies_condition": "prone",
        "save": "STR",
        "dc": 14,
    }
    wave = creatures["hollow_veilrender"]["attacks"][1]
    assert {k: wave[k] for k in ("applies_condition", "save", "dc", "half_on_success")} == {
        "applies_condition": "poisoned",
        "save": "CON",
        "dc": 16,
        "half_on_success": True,
    }
    for key, recharges in {
        "hollow_mawling": ("5-6", "1/encounter"),
        "hollow_weaver": ("1/round", "5-6"),
        "hollow_knight": ("1/round", "5-6", "passive trigger"),
        "hollow_veilrender": ("5-6", "1/encounter"),
    }.items():
        assert tuple(a["recharge"] for a in creatures[key]["actives"]) == recharges
        assert all(
            a["description"]
            for a in creatures[key]["passives"] + creatures[key]["actives"] + creatures[key]["reactions"]
        )


def test_spec_loot_and_seed():
    creatures = {row["id"]: row for row in rows("creatures.json")}
    tables = {row["id"]: row for row in rows("loot_tables.json")}
    items = {row["id"] for row in rows("items.json")}
    materials = {row["id"]: row for row in rows("materials_catalog.json")}
    assert tables and items and materials
    for key, (table_id, expected) in LOOT.items():
        assert creatures[key]["loot_table_id"] == table_id
        table = tables[table_id]
        assert table["hollow_residue"] is True
        assert seed_content.validate_loot_table(table) == []
        actual = tuple(
            (d["item_id"], d["quantity"], d["chance"], tuple((r["skill"], r["tier"]) for r in d["requires"]))
            for d in table["drops"]
        )
        assert actual == expected
        for drop in table["drops"]:
            assert int(drop["item_id"] in items) + int(drop["item_id"] in materials) == 1
            if drop["item_id"] in materials:
                material = materials[drop["item_id"]]
                assert all(
                    material.get(field)
                    for field in ("name", "category", "tier", "rarity", "source", "weight", "description")
                )
                parse_material_row(drop["item_id"], material)

    class Connection:
        def __init__(self):
            self.creatures = set()

        async def execute(self, query, key, data):
            if "INSERT INTO creatures" in query:
                self.creatures.add(key)

    conn = Connection()
    asyncio.run(seed_content.seed(conn))
    assert set(SPEC) <= conn.creatures
