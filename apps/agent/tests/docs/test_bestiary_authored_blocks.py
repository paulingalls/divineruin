"""The appended encounter-creature spec blocks retain their source mechanics."""

import json
import re
from pathlib import Path

from test_creature_catalog_content import assert_sound_first

from creature_schema import validate_creature_stat_block
from world_regions import REGION_IDS

ROOT = Path(__file__).resolve().parents[4]
SPEC = ROOT / "docs/game_mechanics/game_mechanics_bestiary.md"
ENCOUNTERS = ROOT / "content/encounter_templates.json"
MARKER = "## Encounter Creature Stat Blocks"
NAMES = {
    "Hollowed Scout",
    "Hollow Wisp",
    "Hollow Warden",
    "Ashmark Soldier",
    "Ashmark Sergeant",
    "Cultist",
    "Cult Fanatic",
    "Cult Leader",
}
BANDS = {
    1: ((1, 4), (6, 20), (10, 13), (15, 50)),
    2: ((5, 8), (25, 60), (12, 15), (75, 200)),
    3: ((9, 14), (65, 120), (14, 17), (300, 700)),
    4: ((15, 20), (130, 300), (16, 20), (1000, 5000)),
}


def source_enemies():
    enemies = {}
    for encounter in json.loads(ENCOUNTERS.read_text()):
        for enemy in encounter["enemies"]:
            if enemy["name"] in NAMES:
                old = enemies.setdefault(enemy["name"], enemy)
                assert old["action_pool"] == enemy["action_pool"], enemy["name"]
    assert set(enemies) == NAMES
    return enemies


def authored_blocks():
    text = SPEC.read_text()
    assert text.count(MARKER) == 1
    section = text.split(MARKER, 1)[1]
    assert section.strip(), "encounter creature section is empty"
    pieces = re.split(r"(?m)^### (.+)$", section)
    assert pieces[0].strip()
    headings = pieces[1::2]
    assert len(headings) == len(NAMES) and set(headings) == NAMES
    blocks = {}
    for name, body in zip(headings, pieces[2::2], strict=True):
        match = re.fullmatch(r"\s*```json\n(.*?)\n```\s*", body, re.S)
        assert match, name
        blocks[name] = json.loads(match.group(1))
    return blocks


def assert_nonempty_strings(value, path):
    if isinstance(value, str):
        assert value.strip(), path
    elif isinstance(value, dict):
        for key, item in value.items():
            assert_nonempty_strings(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_nonempty_strings(item, f"{path}[{index}]")


def nearest_tier(hp):
    def distance(tier):
        low, high = BANDS[tier][1]
        return max(low - hp, hp - high, 0)

    return min(BANDS, key=distance)


def test_encounter_blocks_are_complete_and_in_nearest_tier():
    sources = source_enemies()
    for name, block in authored_blocks().items():
        assert block["name"] == name
        assert not validate_creature_stat_block(block), (name, validate_creature_stat_block(block))
        assert_nonempty_strings(block, name)
        assert block["attacks"], name
        source = sources[name]
        nearest = nearest_tier(source["hp"])
        assert block["tier"] == nearest, name
        for field, band in zip(("level", "hp", "ac", "xp_reward"), BANDS[nearest], strict=True):
            assert band[0] <= block[field] <= band[1], (name, field)
        assert block["loot_table_id"] == source["loot_table_id"]
        regions = block["behavior"]["environment"]
        assert regions and set(regions) <= set(REGION_IDS), name
        if source["category"].startswith("hollow_"):
            assert block["hollow"]["class"] == source["category"].split("_")[1]
        else:
            assert block["hollow"] is None
        for cue_name, cue in block["narration"].items():
            assert_sound_first(cue, (name, cue_name))
        for group in ("passives", "actives", "reactions"):
            for ability in block[group]:
                assert_sound_first(ability["narration_cue"], (name, ability["name"]))


def test_every_encounter_action_is_in_its_own_block():
    blocks = authored_blocks()
    for name, source in source_enemies().items():
        block = blocks[name]
        actions = {row["name"]: row for row in (*block["attacks"], *block["actives"])}
        assert len(actions) == len(block["attacks"]) + len(block["actives"]), name
        assert "Seizing Grab" not in actions, name
        assert all("escape_dc" not in action for action in block["attacks"]), name
        for action in source["action_pool"]:
            assert action["name"] in actions, (name, action["name"])
            authored = actions[action["name"]]
            if "damage" in action:
                assert authored["damage"] == action["damage"], (name, action["name"])
                assert authored["damage_type"] == action["damage_type"], (name, action["name"])
            if "applies_condition" in action:
                assert authored["applies_condition"] == action["applies_condition"]
                assert authored["save"] == action["save"]
                assert authored["dc"] == action["dc"]
                assert all(
                    str(value) in authored["special"].lower()
                    for value in (action["applies_condition"], action["save"], action["dc"])
                )
            if "kind" in action:
                assert authored["kind"] == action["kind"]
                assert action["kind"] in authored["description"].lower()
        if "signature_ability" in source:
            signature = source["signature_ability"]
            actual = next(row for row in block["actives"] if row["name"] == signature["name"])
            assert signature["save"] in actual["description"].lower()
        if name == "Hollow Warden":
            assert "healing" in actions["Absorb"]["special"].lower()
