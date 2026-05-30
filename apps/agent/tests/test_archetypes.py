"""Tests for archetypes.py — the DB-loaded chassis content config (M2.1).

Mirrors the training_rules loader contract: parse_archetype_row (fail-loud,
shared by the DB loader and the JSON test fixture), set_archetypes (test seam),
get_archetype_chassis (accessor, raises on unknown). The autouse seed_archetypes
conftest fixture populates the chassis from content/archetypes.json before each
test, so chassis-fed math resolves without a DB.
"""

import pytest

from archetypes import (
    Chassis,
    PoolFormula,
    ResourceConfig,
    get_archetype_chassis,
    parse_archetype_row,
    set_archetypes,
)

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

_WARRIOR_ROW = {
    "id": "warrior",
    "hp": {"base": 12, "growth": 5, "category": "martial"},
    "resource": {
        "pattern": "stamina_only",
        "stamina_formula": {"base": 8, "attribute": "constitution", "level_divisor": 1},
        "focus_formula": None,
    },
    "save_proficiencies": ["strength", "constitution"],
    "armor_proficiencies": ["heavy", "medium", "light", "shield"],
    "weapon_proficiencies": ["martial", "simple"],
    "starting_skills": {"options": ["athletics", "perception", "survival"], "num_choices": 3},
}


def test_parse_archetype_row_full_shape():
    c = parse_archetype_row("warrior", _WARRIOR_ROW)
    assert isinstance(c, Chassis)
    assert (c.id, c.hp_base, c.hp_growth, c.hp_category) == ("warrior", 12, 5, "martial")
    assert c.resource == ResourceConfig(
        pattern="stamina_only",
        stamina_formula=PoolFormula(base=8, attribute="constitution", level_divisor=1),
        focus_formula=None,
    )
    assert c.save_proficiencies == ("strength", "constitution")
    assert c.armor_proficiencies == ("heavy", "medium", "light", "shield")
    assert c.weapon_proficiencies == ("martial", "simple")
    assert c.skill_options == ("athletics", "perception", "survival")
    assert c.num_skill_choices == 3


def test_parse_archetype_row_focus_only_has_null_stamina():
    row = {
        **_WARRIOR_ROW,
        "id": "mage",
        "resource": {
            "pattern": "focus_only",
            "stamina_formula": None,
            "focus_formula": {"base": 8, "attribute": "intelligence", "level_divisor": 1},
        },
    }
    c = parse_archetype_row("mage", row)
    assert c.resource.stamina_formula is None
    assert c.resource.focus_formula == PoolFormula(base=8, attribute="intelligence", level_divisor=1)


def test_parse_archetype_row_flat_secondary_pool_level_divisor_zero():
    row = {
        **_WARRIOR_ROW,
        "id": "druid",
        "resource": {
            "pattern": "focus_primary",
            "stamina_formula": {"base": 4, "attribute": "constitution", "level_divisor": 0},
            "focus_formula": {"base": 8, "attribute": "wisdom", "level_divisor": 1},
        },
    }
    c = parse_archetype_row("druid", row)
    assert c.resource.stamina_formula == PoolFormula(base=4, attribute="constitution", level_divisor=0)


def test_parse_archetype_row_fail_loud_names_the_row():
    bad = {k: v for k, v in _WARRIOR_ROW.items() if k != "hp"}
    with pytest.raises(ValueError, match="warrior"):
        parse_archetype_row("warrior", bad)


def test_get_archetype_chassis_resolves_all_18():
    # autouse seed_archetypes (conftest) populates from content/archetypes.json
    for aid in EXPECTED_IDS:
        c = get_archetype_chassis(aid)
        assert isinstance(c, Chassis)
        assert c.id == aid


def test_get_archetype_chassis_unknown_raises():
    with pytest.raises(ValueError, match="unknown_archetype"):
        get_archetype_chassis("unknown_archetype")


def test_set_archetypes_seam_replaces_state():
    set_archetypes({"warrior": parse_archetype_row("warrior", _WARRIOR_ROW)})
    assert get_archetype_chassis("warrior").hp_base == 12
    with pytest.raises(ValueError):
        get_archetype_chassis("mage")
