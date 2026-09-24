"""Pins for the eight encounter creatures' signed-off catalog blocks."""

import asyncio
import importlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

from creature_schema import validate_creature_stat_block

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
seed_content = importlib.import_module("seed_content")

PINS = {
    "hollowed_scout": (
        "hollow",
        2,
        5,
        32,
        13,
        125,
        "loot_hollow_rend",
        (
            ("Corrupted Blade", "1d8+2", None, None, None),
            ("Hollow Echo", "1d6", None, None, None),
            ("Relentless Advance", "1d4", None, None, None),
        ),
        (),
        None,
        ("radiant", "blessed_weapons", "turn_undead_hollow"),
    ),
    "hollow_wisp": (
        "hollow",
        1,
        3,
        18,
        12,
        40,
        "loot_hollow_drift",
        (("Draining Touch", "2d6", None, None, None), ("Hollow Drain", "1d8", None, None, None)),
        (),
        None,
        ("radiant", "fire", "area_damage"),
    ),
    "hollow_warden": (
        "hollow",
        2,
        7,
        55,
        15,
        200,
        "loot_hollow_warden",
        (
            ("Void Lash", "2d6", None, None, None),
            ("Reality Fracture", "1d8", None, None, None),
            ("Absorb", "1d6", None, None, None),
        ),
        (),
        ("Reality Collapse", "wisdom"),
        ("radiant", "blessed_weapons", "divine"),
    ),
    "ashmark_soldier": (
        "humanoid",
        2,
        5,
        28,
        13,
        100,
        "loot_humanoid_soldier",
        (("Longsword", "1d8+2", None, None, None), ("Shield Bash", "0", "prone", "strength", 12)),
        (),
        None,
        None,
    ),
    "ashmark_sergeant": (
        "humanoid",
        2,
        6,
        38,
        14,
        150,
        "loot_humanoid_soldier",
        (("Greatsword", "2d6+2", None, None, None),),
        (("Rally", "command", ("buff",)), ("Accusation", "accusation", ())),
        None,
        None,
    ),
    "cultist": (
        "humanoid",
        1,
        1,
        10,
        11,
        20,
        "loot_humanoid_cultist",
        (("Ritual Dagger", "1d4+1", None, None, None),),
        (),
        None,
        None,
    ),
    "cult_fanatic": (
        "humanoid",
        1,
        3,
        19,
        13,
        45,
        "loot_humanoid_cultist",
        (("Mace", "1d6", None, None, None), ("Inflict Wounds", "2d8", None, None, None)),
        (("Bless", "command", ("buff",)),),
        None,
        None,
    ),
    "cult_leader": (
        "humanoid",
        2,
        8,
        48,
        14,
        180,
        "loot_cult_leader",
        (
            ("Shadow Bolt", "2d6", None, None, None),
            ("Hold Person", "0", "paralyzed", "wisdom", 12),
            ("Dark Pulse", "1d10", None, None, None),
        ),
        (),
        ("Mantle of Ruin", "constitution"),
        None,
    ),
}


def authored_blocks():
    source = (ROOT / "docs/game_mechanics/game_mechanics_bestiary.md").read_text()
    marker = "## Encounter Creature Stat Blocks"
    assert source.count(marker) == 1
    section = source.split(marker, 1)[1]
    matches = re.findall(r"(?ms)^### ([^\n]+)\n\s*```json\n(.*?)\n```", section)
    assert len(matches) == len(PINS)
    blocks = [json.loads(raw) for _, raw in matches]
    assert len({name for name, _ in matches}) == len(matches)
    assert all(name == block["name"] for (name, _), block in zip(matches, blocks, strict=True))
    assert Counter(block["id"] for block in blocks) == Counter({creature_id: 1 for creature_id in PINS})
    return {block["id"]: block for block in blocks}


def assert_pins(row, pin):
    category, tier, level, hp, ac, xp, loot, attacks, actives, signature, vulnerabilities = pin
    assert (
        row["category"],
        row["tier"],
        row["level"],
        row["hp"],
        row["ac"],
        row["xp_reward"],
        row["loot_table_id"],
    ) == (category, tier, level, hp, ac, xp, loot)
    assert (
        tuple((a["name"], a["damage"], a.get("applies_condition"), a.get("save"), a.get("dc")) for a in row["attacks"])
        == attacks
    )
    assert tuple((a["name"], a.get("kind"), tuple(a.get("properties", ()))) for a in row["actives"]) == actives
    assert all(not {"properties", "half_on_success", "escape_dc"} & a.keys() for a in row["attacks"])
    assert "resistance_tags" not in row
    actual_signature = row.get("signature_ability")
    assert ((actual_signature["name"], actual_signature.get("save")) if actual_signature else None) == signature
    assert (tuple(row["hollow"]["vulnerable_to"]) if row["hollow"] else None) == vulnerabilities


def test_authored_catalog_rows_match_spec_and_pins():
    blocks = authored_blocks()
    rows = json.loads((ROOT / "content/creatures.json").read_text())
    counts = Counter(row["id"] for row in rows)
    loot_ids = {row["id"] for row in json.loads((ROOT / "content/loot_tables.json").read_text())}
    for creature_id, pin in PINS.items():
        assert counts[creature_id] == 1
        block = blocks[creature_id]
        row = next(row for row in rows if row["id"] == creature_id)
        assert_pins(block, pin)
        assert_pins(row, pin)
        assert row == block
        assert row["loot_table_id"] in loot_ids
        assert validate_creature_stat_block(row) == []


def test_encounter_rows_are_submitted_by_seed():
    class Connection:
        def __init__(self):
            self.creatures = set()

        async def execute(self, query, key, data):
            if "INSERT INTO creatures" in query:
                self.creatures.add(key)

    conn = Connection()
    asyncio.run(seed_content.seed(conn))
    assert set(PINS) <= conn.creatures
