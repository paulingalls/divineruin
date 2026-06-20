"""Unit coverage for the pure status-condition module (M4.3, story-001).

Catalog and behavior mirror docs/game_mechanics/game_mechanics_combat.md
§Status Effects (L263-322). The module is pure: every test below constructs
plain inputs and asserts on returned values — no DB, no RNG, no combat state.
"""

import pytest

from conditions import (
    CONDITION_CATALOG,
    ConditionSpec,
)

# The 21 conditions of the spec catalog, by snake_case label.
ALL_CONDITIONS = [
    "wounded",
    "stunned",
    "prone",
    "grappled",
    "restrained",
    "incapacitated",
    "paralyzed",
    "poisoned",
    "blessed",
    "shielded",
    "enraged",
    "exhausted",
    "blinded",
    "frightened",
    "charmed",
    "deafened",
    "shaken",
    "petrified",
    "cursed",
    "inspired",
    "hollowed",
]


# --- Slice 1: catalog completeness ---


def test_catalog_has_all_21_conditions():
    assert set(CONDITION_CATALOG) == set(ALL_CONDITIONS)
    assert len(CONDITION_CATALOG) == 21


@pytest.mark.parametrize("condition_type", ALL_CONDITIONS)
def test_every_catalog_entry_is_a_condition_spec(condition_type):
    spec = CONDITION_CATALOG[condition_type]
    assert isinstance(spec, ConditionSpec)
    # Each entry must declare how it clears (mirrors the doc's "Cleared By" column).
    assert spec.clearance, f"{condition_type} missing clearance"


def test_exhausted_is_stackable_with_cap_5():
    spec = CONDITION_CATALOG["exhausted"]
    assert spec.stackable is True
    assert spec.default_max_stacks == 5


def test_consumed_conditions_persist_field_is_false_by_default():
    # Blessed/Inspired/Shaken are consumed-on-use; they do not survive an encounter.
    for c in ("blessed", "inspired", "shaken"):
        assert CONDITION_CATALOG[c].persists_across_encounters is False


def test_cross_encounter_conditions_persist():
    # Wounded (until long rest), Exhausted (per long rest), Hollowed (Greater Restoration)
    # outlive a single encounter.
    for c in ("wounded", "exhausted", "hollowed"):
        assert CONDITION_CATALOG[c].persists_across_encounters is True
