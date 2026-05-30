"""Content tests for content/archetypes.json — the M2.1 chassis SSOT.

These read the raw JSON file (NOT a loader; the loader lives in archetypes.py).
HP/resource values are pinned by test_hp_scaling.py / test_rules_pools.py (which
assert the loaded chassis against the historically-correct numbers); this module
checks the JSON's structure, roster (still parity-checked against CLASSES ids),
and the armor/weapon proficiency vocabularies (which have no other automated
check). Saves/skills are now owned solely by archetypes.json (story-004 dropped
them from CLASSES), so there is no longer a CLASSES copy of those to assert
parity against.
"""

import json
import re
from pathlib import Path

import pytest

from creation_classes import CLASSES

ARCHETYPES_JSON = Path(__file__).resolve().parents[3] / "content" / "archetypes.json"

EXPECTED_IDS = {
    "warrior",
    "guardian",
    "skirmisher",
    "mage",
    "artificer",
    "seeker",
    "druid",
    "beastcaller",
    "warden",
    "cleric",
    "paladin",
    "oracle",
    "rogue",
    "spy",
    "whisper",
    "bard",
    "diplomat",
    "marshal",
}

REQUIRED_KEYS = {
    "id",
    "hp",
    "resource",
    "save_proficiencies",
    "armor_proficiencies",
    "weapon_proficiencies",
    "starting_skills",
}

# Armor is a naturally closed vocabulary (classes + non-metal qualifiers + the
# unarmored sentinel). Weapon tokens are open-ended (specific weapon ids), so
# they are checked only for well-formedness. story-002/003 loaders will own the
# fail-loud closed-vocabulary validation; until then this catches typos/casing.
ARMOR_VOCAB = {
    "heavy",
    "medium",
    "light",
    "shield",
    "heavy_nonmetal",
    "medium_nonmetal",
    "light_nonmetal",
    "shield_nonmetal",
    "none",
}
TOKEN_RE = re.compile(r"^[a-z][a-z_]*$")


@pytest.fixture(scope="module")
def archetypes() -> dict[str, dict]:
    rows = json.loads(ARCHETYPES_JSON.read_text())
    assert isinstance(rows, list), "archetypes.json must be a top-level array"
    by_id = {row["id"]: row for row in rows}
    assert len(by_id) == len(rows), "duplicate archetype id in archetypes.json"
    return by_id


def test_all_18_archetypes_present(archetypes):
    assert set(archetypes) == EXPECTED_IDS
    # JSON roster agrees with the CLASSES creation-flow roster (same 18 ids).
    assert set(archetypes) == set(CLASSES)


def test_each_row_has_required_keys(archetypes):
    for aid, row in archetypes.items():
        assert set(row) >= REQUIRED_KEYS, f"{aid} missing keys: {REQUIRED_KEYS - set(row)}"
        assert row["id"] == aid


def test_armor_proficiencies_in_closed_vocab(archetypes):
    for aid, row in archetypes.items():
        armor = row["armor_proficiencies"]
        assert isinstance(armor, list) and armor, f"{aid} armor_proficiencies must be a non-empty list"
        unknown = [t for t in armor if t not in ARMOR_VOCAB]
        assert not unknown, f"{aid} armor_proficiencies has out-of-vocab token(s): {unknown}"


def test_weapon_proficiencies_well_formed(archetypes):
    for aid, row in archetypes.items():
        weapons = row["weapon_proficiencies"]
        assert isinstance(weapons, list) and weapons, f"{aid} weapon_proficiencies must be a non-empty list"
        malformed = [t for t in weapons if not (isinstance(t, str) and TOKEN_RE.match(t))]
        assert not malformed, f"{aid} weapon_proficiencies has malformed token(s): {malformed}"
