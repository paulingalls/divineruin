"""Spec pins for natural bestiary entries."""

import asyncio
import importlib
import json
import re
import sys
from pathlib import Path

import pytest

# Re-exported so pytest collects them: the pins module's name does not match test_*.py.
from creature_spec_pins_hollow_rend_wrack import (  # noqa: F401
    test_spec_loot_and_seed,
    test_spec_mechanics,
    test_spec_stats_hollow_and_attacks,
)
from creature_spec_pins_steppe_keldaran_sunward import ABILITIES as NEW_ABILITIES
from creature_spec_pins_steppe_keldaran_sunward import BEHAVIOR as NEW_BEHAVIOR
from creature_spec_pins_steppe_keldaran_sunward import LOOT as NEW_LOOT
from creature_spec_pins_steppe_keldaran_sunward import SPEC as NEW_SPEC
from creature_spec_pins_underground_multi_region import ABILITIES as FINAL_ABILITIES
from creature_spec_pins_underground_multi_region import BEHAVIOR as FINAL_BEHAVIOR
from creature_spec_pins_underground_multi_region import LOOT as FINAL_LOOT
from creature_spec_pins_underground_multi_region import MULTIATTACK as FINAL_MULTIATTACK
from creature_spec_pins_underground_multi_region import SPEC as FINAL_SPEC

from creature_schema import validate_creature_stat_block

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
seed_content = importlib.import_module("seed_content")

SPEC = {
    "grey_wolf": (
        "beast",
        1,
        1,
        11,
        12,
        40,
        25,
        (12, 14, 12, 3, 12, 6),
        ("DEX", "WIS"),
        (("Bite", "melee", 5, 4, "1d6+2", "piercing", "DC 11 STR save or knocked prone"),),
        "greyvale",
        ("greyvale", "thornveld", "drathian_steppe", "keldaran_mountains"),
    ),
    "wild_boar": (
        "beast",
        1,
        1,
        14,
        11,
        30,
        25,
        (14, 10, 14, 2, 10, 4),
        ("CON",),
        (("Tusk", "melee", 5, 4, "1d6+2", "slashing", "If charged 15+ ft before attack: +1d6 damage"),),
        "greyvale",
        ("greyvale", "thornveld"),
    ),
    "giant_spider": (
        "beast",
        1,
        2,
        18,
        13,
        30,
        50,
        (12, 16, 12, 2, 11, 4),
        ("DEX",),
        (
            ("Bite", "melee", 5, 5, "1d8+3", "piercing", "DC 12 CON save or Poisoned 1 hour + 1d6 poison damage"),
            ("Web", "ranged", 30, 5, "0", "none", "Target Restrained (STR DC 12 or slash through, AC 10, 5 HP)"),
        ),
        "greyvale",
        ("greyvale", "underground", "thornveld"),
    ),
    "bandit": (
        "humanoid",
        1,
        2,
        16,
        13,
        30,
        50,
        (12, 14, 12, 10, 10, 10),
        ("DEX",),
        (
            ("Short Sword", "melee", 5, 4, "1d6+2", "slashing", None),
            ("Light Crossbow", "ranged", 80, 4, "1d8+2", "piercing", None),
        ),
        "greyvale",
        ("greyvale",),
    ),
    "thornveld_stalker": (
        "beast",
        1,
        2,
        22,
        14,
        40,
        50,
        (14, 16, 12, 4, 14, 6),
        ("DEX", "WIS"),
        (
            ("Claw", "melee", 5, 5, "1d6+3", "slashing", None),
            (
                "Pounce",
                "melee",
                5,
                5,
                "1d8+3",
                "slashing",
                "Requires 20 ft movement. Target DEX save DC 13 or knocked prone. If prone: free bite attack (1d6+3)",
            ),
        ),
        "thornveld",
        ("thornveld", "greyvale"),
    ),
    "corrupted_treant": (
        "elemental",
        2,
        6,
        55,
        14,
        20,
        200,
        (18, 6, 16, 8, 14, 8),
        ("STR", "CON"),
        (
            ("Slam", "melee", 10, 7, "2d8+4", "bludgeoning", "Target pushed 10 ft"),
            ("Thorn Barrage", "area", 30, 0, "2d6", "piercing", "DEX save DC 14. 15 ft cone. Half on success"),
        ),
        "thornveld",
        ("thornveld", "greyvale"),
    ),
}

# Spec columns: drop id, quantity, chance, requirement. Coin and varies are omitted.
LOOT = {
    "grey_wolf": (
        ("wolf_pelt", 1, 1.0, "survival:trained"),
        ("wolf_fangs", "1d4", 1.0, None),
        ("wolf_meat", 2, 1.0, "survival:trained"),
    ),
    "wild_boar": (
        ("boar_hide", 1, 1.0, "survival:trained"),
        ("boar_tusks", 2, 1.0, None),
        ("boar_meat", 4, 1.0, "survival:trained"),
    ),
    "giant_spider": (
        ("spider_silk", "1d4", 0.75, "survival:trained"),
        ("venom_sac", 1, 0.5, "survival:expert"),
        ("spider_chitin", "1d4", 1.0, None),
    ),
    "bandit": (("leather_armor_basic", 1, 0.5, None), ("shortsword_basic", 1, 0.75, None)),
    "thornveld_stalker": (("stalker_pelt", 1, 1.0, "survival:trained"), ("stalker_claws", 2, 1.0, None)),
    "corrupted_treant": (
        ("ironwood_bark", "1d4", 1.0, "survival:trained"),
        ("corrupted_heartwood", 1, 0.5, "crafting:expert"),
        ("thornveld_amber", 1, 0.25, "survival:expert"),
    ),
}

BEHAVIOR = {
    "grey_wolf": (
        "Packs surround prey. Target prone creatures. Retreat if alpha falls.",
        "Flees at half pack size.",
        "Pack of 3-6",
        ("Greyvale forest", "Thornveld edge", "Drathian Steppe", "mountain foothills"),
        ("Pack Tactics", "Keen Hearing and Smell"),
        (),
    ),
    "wild_boar": (
        "Territorial. Charges at intruders. Does not pursue beyond territory.",
        "Fights to death defending territory. Flees if encountered outside territory.",
        "Solitary or sounder of 2-4",
        ("Greyvale farmlands", "forest edges", "Thornveld outer"),
        ("Relentless", "Charge"),
        (),
    ),
    "giant_spider": (
        "Ambush predator. Webs exits, waits on ceiling, drops on webbed prey. Climbs 30 ft. Retreats to web if threatened in open.",
        "Flees if web is destroyed.",
        "Solitary or pair (shared web)",
        ("Greyvale ruins", "caves", "dungeons", "Thornveld canopy"),
        ("Spider Climb", "Web Sense", "Darkvision"),
        (),
    ),
    "bandit": (
        "Ambush from cover. Focus downed targets. Demand surrender before attacking if outnumbered.",
        "Flees at half HP or if leader falls. Surrenders if clearly outmatched.",
        "Gang of 3-6, often with 1 Bandit Captain (Tier 2)",
        ("Roads between settlements", "forest ambush points", "ruins"),
        (),
        ("Dirty Fighting",),
    ),
    "thornveld_stalker": (
        "Ambush predator. Climbs 20 ft, stalks from trees, and pounces on isolated targets. Will not attack groups of 4+.",
        "Flees if first pounce fails.",
        "Solitary",
        ("Thornveld", "deep Greyvale forest"),
        ("Keen Smell", "Forest Camouflage"),
        (),
    ),
    "corrupted_treant": (
        "Territorial guardian of corrupted groves. Twisted by proximity to Hollow corruption; still natural, but warped and hostile. Prioritizes fire-users as threats.",
        "Fights to death defending its grove. Will not pursue beyond 100 ft of its tree.",
        "Solitary (guarding 2-3 normal trees that are its grove)",
        ("Thornveld corruption edges", "Greyvale where Hollow meets forest"),
        ("Vulnerability to Fire", "Resistance", "Rooted Aura"),
        ("Entangling Roots",),
    ),
}

ABILITIES = {
    "grey_wolf": (
        ("Advantage if an ally is within 5 ft of the target.", "Advantage on related Perception checks."),
        (),
    ),
    "wild_boar": (
        (
            "1/day, if reduced to 0 HP by an attack dealing 7 or less damage, drop to 1 HP instead.",
            "Bonus damage after moving 15 ft before a tusk attack.",
        ),
        (),
    ),
    "giant_spider": (
        (
            "Climb 30 ft on surfaces including ceilings.",
            "Knows location of any creature touching its web.",
            "Darkvision 60 ft.",
        ),
        (),
    ),
    "bandit": (
        (),
        (
            (
                "1/encounter: throw dirt or sand. Target is Blinded for 1 round unless it passes a DEX save DC 12.",
                "1/encounter",
            ),
        ),
    ),
    "thornveld_stalker": (("Advantage on Perception checks by smell.", "Advantage on Stealth in forest terrain."), ()),
    "corrupted_treant": (
        (
            "Takes double fire damage.",
            "Resists bludgeoning and piercing damage.",
            "Plants within 30 ft grow aggressively; the area is difficult terrain.",
        ),
        (("All creatures within 15 ft: STR save DC 14 or Restrained. The ground erupts with roots.", "Recharge 5-6"),),
    ),
}

LOOT = {
    key: tuple(
        (item, quantity, chance, () if requirement is None else (tuple(requirement.split(":")),))
        for item, quantity, chance, requirement in drops
    )
    for key, drops in LOOT.items()
}
SPEC.update(NEW_SPEC)
LOOT.update(NEW_LOOT)
BEHAVIOR.update(NEW_BEHAVIOR)
ABILITIES.update(NEW_ABILITIES)
SPEC.update(FINAL_SPEC)
LOOT.update(FINAL_LOOT)
BEHAVIOR.update(FINAL_BEHAVIOR)
ABILITIES.update(FINAL_ABILITIES)

SOUND_OR_SMELL_LEXICON = (
    "howl",
    "whine",
    "pant",
    "snuffle",
    "squeal",
    "snort",
    "click",
    "hiss",
    "scrape",
    "crack",
    "rustle",
    "sniff",
    "grind",
    "thud",
    "whistle",
    "breath",
    "smell",
    "scent",
    "reek",
    "stink",
    "odor",
    "clatter",
    "twang",
    "yelp",
    "growl",
    "grunt",
    "chitter",
    "snap",
    "creak",
    "drip",
    "squelch",
    "crunch",
    "rasp",
    "screech",
    "rattle",
    "gurgle",
    "splash",
    "crackle",
    "slosh",
    "groan",
    "hum",
)
SIGHT_LEXICON = (
    "see",
    "sight",
    "look",
    "glimpse",
    "spot",
    "watch",
    "visible",
    "shape",
    "shadow",
    "silhouette",
    "eyes",
    "gaze",
)


def catalog(name):
    return json.loads((ROOT / "content" / name).read_text())


def named_rows(rows):
    by_id = {row["id"]: row for row in rows}
    assert len(by_id) == len(rows)
    assert set(SPEC) <= by_id.keys()
    return by_id


def test_spec_stats_regions_and_behavior():
    rows = named_rows(catalog("creatures.json"))
    for key, expected in SPEC.items():
        row = rows[key]
        actual = (
            row["category"],
            row["tier"],
            row["level"],
            row["hp"],
            row["ac"],
            row["speed"],
            row["xp_reward"],
            tuple(row["attributes"][attr] for attr in ("STR", "DEX", "CON", "INT", "WIS", "CHA")),
            tuple(row["save_proficiencies"]),
            tuple(
                tuple(
                    attack[field] for field in ("name", "type", "reach", "to_hit", "damage", "damage_type", "special")
                )
                for attack in row["attacks"]
            ),
            row["home_region"],
            tuple(row["regions"]),
        )
        assert actual == expected, key
        assert row["multiattack"] == FINAL_MULTIATTACK.get(
            key, "2 attacks — one Bite and one Tail" if key == "cave_wyrm" else None
        )
        assert row["hollow"] is None and row["reactions"] == []
        behavior = row["behavior"]
        assert (
            behavior["tactics"],
            behavior["morale"],
            behavior["group_size"],
            tuple(behavior["environment"]),
            tuple(ability["name"] for ability in row["passives"]),
            tuple(ability["name"] for ability in row["actives"]),
        ) == BEHAVIOR[key]
        assert (
            tuple(ability["description"] for ability in row["passives"]),
            tuple((ability["description"], ability["recharge"]) for ability in row["actives"]),
        ) == ABILITIES[key]
    assert {attack["name"] for attack in rows["bandit"]["attacks"]} == {"Short Sword", "Light Crossbow"}
    assert {attack["name"] for attack in rows["bandit_captain"]["attacks"]} == {"Longsword", "Heavy Crossbow"}
    assert {attack["name"] for attack in rows["troll"]["attacks"]} == {"Claw", "Bite"}
    greyvale = [rows[key] for key in SPEC if rows[key]["home_region"] == "greyvale"]
    assert greyvale
    assert all(row["tier"] == 1 for row in greyvale)
    keldaran = [rows[key] for key in SPEC if rows[key]["home_region"] == "keldaran_mountains"]
    assert any(row["id"] == "war_golem" and row["tier"] == 3 for row in keldaran)


def drop_rows(table):
    return tuple(
        (
            drop["item_id"],
            drop["quantity"],
            drop["chance"],
            tuple((r["skill"], r["tier"]) for r in drop["requires"]),
        )
        for drop in table["drops"]
    )


def test_spec_loot_and_owners():
    rows = named_rows(catalog("creatures.json"))
    tables = {row["id"]: row for row in catalog("loot_tables.json")}
    items = {row["id"] for row in catalog("items.json")}
    materials = {row["id"] for row in catalog("materials_catalog.json")}
    assert items and materials
    for key, expected in LOOT.items():
        table = tables[rows[key]["loot_table_id"]]
        assert table["id"] == ("loot_bandit_captain_catalog" if key == "bandit_captain" else f"loot_{key}")
        assert seed_content.validate_loot_table(table) == []
        assert drop_rows(table) == expected, key
        assert all(int(drop["item_id"] in items) + int(drop["item_id"] in materials) == 1 for drop in table["drops"])


def test_war_golem_four_spec_drops():
    tables = {row["id"]: row for row in catalog("loot_tables.json")}
    assert drop_rows(tables["loot_war_golem"]) == NEW_LOOT["war_golem"]


SENSORY = re.compile(r"\b(?:" + "|".join(SOUND_OR_SMELL_LEXICON) + r")(?:s|ed|ing)?\b", re.I)
SIGHT = re.compile(r"\b(?:" + "|".join(SIGHT_LEXICON) + r")(?:s|ed|ing)?\b", re.I)


def assert_sound_first(cue, label):
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", cue) if part.strip()]
    assert 1 <= len(sentences) <= 3, label
    sound = SENSORY.search(sentences[0])
    vision = SIGHT.search(sentences[0])
    assert sound and (not vision or sound.start() < vision.start()), label


def test_narration_opens_with_sound_or_smell():
    rows = named_rows(catalog("creatures.json"))
    assert rows
    assert {"hollow_mawling", "hollow_weaver", "hollow_knight", "hollow_veilrender"} <= rows.keys()
    for key in rows:
        for cue_name in ("first_sighting", "attack_cue", "wounded_cue", "death_cue", "ambient_cue"):
            assert_sound_first(rows[key]["narration"][cue_name], (key, cue_name))
        audio = rows[key]["audio"]
        assert all(audio[slot] and audio[slot].split()[0] != key for slot in ("ambient", "attack", "hit", "death")), key


def test_sound_first_check_rejects_sight_first_and_long_cues():
    assert_sound_first("A low howl rolls through the brush. Grey shapes close the gap.", "sound first")
    for cue in (
        "Grey shapes close the gap. A low howl follows.",
        "You see a wolf howl.",
        "Pale fur flickers between the pines.",
        "A howl. A growl. A snap. A yelp.",
        "",
    ):
        with pytest.raises(AssertionError):
            assert_sound_first(cue, cue)


def test_real_validators_and_seed_submission():
    rows = named_rows(catalog("creatures.json"))
    for key in SPEC:
        assert validate_creature_stat_block(rows[key]) == []

    class RecordingConnection:
        def __init__(self):
            self.creatures = set()

        async def execute(self, query, key, data):
            if "INSERT INTO creatures" in query:
                self.creatures.add(key)

    conn = RecordingConnection()
    asyncio.run(seed_content.seed(conn))
    assert set(SPEC) <= conn.creatures
