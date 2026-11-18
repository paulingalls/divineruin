"""Malformed catalog traits and saved suppression must fail before mechanics are lost."""

from copy import deepcopy

import pytest
from combat.test_veilrender import boss_state

from combat_state import CombatState
from creature_schema import validate_creature_stat_block


@pytest.mark.parametrize(
    "key,field,value",
    [
        ("corruption_field", "dc", True),
        ("corruption_field", "save", "bogus"),
        ("corruption_field", "damage", "garbage"),
        ("corruption_field", "damage_type", "bogus"),
        ("corruption_field", "extra", 1),
        ("regeneration", "hp", True),
        ("regeneration", "hp", 0),
        ("regeneration", "narration_cue", ""),
        ("regeneration", "suppressed_cue", " "),
        ("regeneration", "resumed_cue", None),
        ("regeneration", "extra", 1),
    ],
)
def test_catalog_traits_fail_loud(key, field, value):
    _, _, row = boss_state()
    assert validate_creature_stat_block(row) == []
    row[key][field] = value
    assert validate_creature_stat_block(row)


@pytest.mark.parametrize(
    "key,value",
    [
        ("regeneration", None),
        ("corruption_field", None),
        ("radiant_suppression_pending", 1),
        ("regeneration_suppressed", "false"),
        ("veilrender_turn_round", True),
        ("veilrender_turn_round", 2),
        ("veilrender_turn_round", 0),
    ],
)
def test_snapshot_traits_fail_loud(key, value):
    state, _, _ = boss_state()
    snapshot = state.to_dict()
    assert CombatState.from_dict(snapshot).to_dict() == snapshot
    snapshot["participants"][1][key] = value
    with pytest.raises(ValueError):
        CombatState.from_dict(snapshot)


@pytest.mark.parametrize("condition,duration", [("poisoned", None), ("prone", 0), ("hollowed", False)])
def test_permanent_rider_floor(condition, duration):
    _, _, row = boss_state()
    row["actives"][0]["conditions_on_failure"] = [{"applies_condition": condition, "duration": duration}]
    assert validate_creature_stat_block(row)


def test_missing_nested_fields():
    _, _, row = boss_state()
    for key in ("regeneration", "corruption_field"):
        for field in row[key]:
            broken = deepcopy(row)
            del broken[key][field]
            assert validate_creature_stat_block(broken)
