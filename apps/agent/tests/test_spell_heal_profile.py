"""Heal profiles at the real catalog parsing boundary."""

import json
from pathlib import Path

import pytest

from spells import parse_spell_row

PROFILES = {
    "divine_heal_wounds": {"dice": "1d8", "attribute": "wisdom", "recipients": "single"},
    "primal_healing_touch": {"dice": "1d8", "attribute": "wisdom", "recipients": "single"},
    "divine_mass_heal": {"dice": "2d8", "attribute": "wisdom", "recipients": "all_allies"},
    "divine_prayer_of_healing": {
        "dice": "2d8",
        "attribute": "wisdom",
        "recipients": "selected",
        "out_of_combat_only": True,
    },
    "primal_regenerate": {"dice": "4d8+15", "recipients": "single"},
}
DEATH_SPELLS = {"divine_revivify", "divine_resurrection"}
GOODBERRY = "primal_goodberry"


@pytest.fixture(scope="module")
def catalog():
    path = Path(__file__).resolve().parents[3] / "content/spells.json"
    return {row["id"]: row for row in json.loads(path.read_text())}


def test_entire_healing_inventory_has_authored_formulas_or_an_explicit_exception(catalog):
    parsed = {id_: parse_spell_row(id_, row) for id_, row in catalog.items()}
    assert len(parsed) == 87
    assert {id_ for id_, spell in parsed.items() if spell.healing} == PROFILES.keys() | DEATH_SPELLS | {GOODBERRY}
    assert {id_: spell.heal for id_, spell in parsed.items() if spell.heal is not None} == PROFILES
    assert parsed["divine_prayer_of_healing"].max_targets == 6
    assert parsed[GOODBERRY].creates_item == {"item_id": "goodberry", "quantity": 5}


@pytest.mark.parametrize(
    "profile,cap",
    [
        (None, None),
        ([], None),
        ({}, None),
        ({"recipients": "single"}, None),
        ({"dice": "1d8"}, None),
        ({"dice": "0d8", "recipients": "single"}, None),
        ({"dice": "1d8-2", "recipients": "single"}, None),
        ({"dice": "1d8", "recipients": []}, None),
        ({"dice": "1d8", "recipients": "enemy"}, None),
        ({"dice": "1d8", "recipients": "single", "attribute": "luck"}, None),
        ({"dice": "1d8", "recipients": "single", "out_of_combat_only": 1}, None),
        ({"dice": "1d8", "recipients": "single", "bonus": 1}, None),
        ({"dice": "1d8", "recipients": "selected"}, None),
        ({"dice": "1d8", "recipients": "all_allies"}, 6),
    ],
)
def test_malformed_heal_names_the_spell(catalog, profile, cap):
    spell_id = "divine_heal_wounds"
    with pytest.raises(ValueError, match=f"{spell_id}.*heal"):
        parse_spell_row(spell_id, {**catalog[spell_id], "heal": profile, "max_targets": cap})


@pytest.mark.parametrize(
    "profile",
    [
        None,
        {},
        {"item_id": "goodberry", "quantity": True},
        {"item_id": "goodberry", "quantity": 0},
        {"item_id": " ", "quantity": 5},
    ],
)
def test_goodberry_requires_a_valid_item_profile(catalog, profile):
    with pytest.raises(ValueError, match=GOODBERRY):
        parse_spell_row(GOODBERRY, {**catalog[GOODBERRY], "creates_item": profile})


def test_an_ordinary_heal_cannot_use_an_item_profile_as_its_exception(catalog):
    row = {**catalog[GOODBERRY], "id": "renamed_heal"}
    with pytest.raises(ValueError, match=r"renamed_heal.*heal"):
        parse_spell_row(row["id"], row)
