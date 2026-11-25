import json
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


@pytest.fixture(scope="module")
def archetypes() -> dict[str, dict]:
    rows = json.loads(ARCHETYPES_JSON.read_text())
    assert isinstance(rows, list), "archetypes.json must be a top-level array"
    by_id = {row["id"]: row for row in rows}
    assert len(by_id) == len(rows), "duplicate archetype id in archetypes.json"
    return by_id


def test_all_18_archetypes_present(archetypes):
    assert set(archetypes) == EXPECTED_IDS
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
