"""Resurrection: cost application + 4-tier anchors (M4.4 story-003).

Pure pieces of the core resurrection loop: attribute selectors that resolve a DeathCost's
attribute_target (lowest/primary/highest) to a concrete attribute, apply_death_cost which turns a
DeathCost into the persistence deltas, and resolve_resurrection_anchor's 4-tier hierarchy. The
orchestration (trigger_character_death) and real-PG round-trip live alongside / in the persistence
suite. Spec: docs/game_mechanics/game_mechanics_combat.md §The Cost Engine + §Resurrection Location."""

from death_cost import determine_death_cost
from resurrection import (
    apply_death_cost,
    highest_attribute,
    lowest_attribute,
)

_ATTRS = {
    "strength": 14,
    "dexterity": 12,
    "constitution": 13,
    "intelligence": 10,
    "wisdom": 11,
    "charisma": 8,
}


class TestAttributeSelectors:
    def test_lowest_attribute(self):
        assert lowest_attribute(_ATTRS) == "charisma"

    def test_highest_attribute(self):
        assert highest_attribute(_ATTRS) == "strength"

    def test_lowest_tie_breaks_by_canonical_order(self):
        tie = {"strength": 10, "dexterity": 10, "constitution": 15}
        assert lowest_attribute(tie) == "strength"  # str before dex in canonical order

    def test_highest_tie_breaks_by_canonical_order(self):
        tie = {"strength": 15, "dexterity": 15, "constitution": 10}
        assert highest_attribute(tie) == "strength"


class TestApplyDeathCost:
    def _player(self, cls="warrior"):
        return {"class": cls, "attributes": dict(_ATTRS), "level": 5}

    def test_gentle_applies_no_attribute_or_maxhp(self):
        cost = determine_death_cost(1, level=5)
        out = apply_death_cost(self._player(), cost)
        assert out["attribute"] is None
        assert out["attribute_delta"] == 0
        assert out["maxhp_override_delta"] == 0

    def test_moderate_penalizes_lowest_attribute(self):
        cost = determine_death_cost(2, level=5)
        out = apply_death_cost(self._player(), cost)
        assert out["attribute"] == "charisma"  # lowest
        assert out["attribute_delta"] == -1

    def test_severe_penalizes_class_primary_attribute(self):
        cost = determine_death_cost(3, level=5)
        out = apply_death_cost(self._player(cls="warrior"), cost)
        assert out["attribute"] == "strength"  # warrior primary
        assert out["attribute_delta"] == -1

    def test_severe_primary_uses_class_mapping_not_highest(self):
        # A mage's primary is intelligence even though strength is the highest score here.
        cost = determine_death_cost(4, level=5)
        out = apply_death_cost(self._player(cls="mage"), cost)
        assert out["attribute"] == "intelligence"

    def test_devastating_penalizes_highest_by_two(self):
        cost = determine_death_cost(5, level=5)
        out = apply_death_cost(self._player(), cost)
        assert out["attribute"] == "strength"  # highest
        assert out["attribute_delta"] == -2
        assert out["maxhp_override_delta"] == 0  # below death 7

    def test_death_seven_adds_maxhp_override_per_level(self):
        cost = determine_death_cost(7, level=10)
        out = apply_death_cost(self._player(), cost)
        assert out["maxhp_override_delta"] == -10  # -1 per level

    def test_primary_falls_back_to_highest_for_unknown_class(self):
        cost = determine_death_cost(3, level=5)
        out = apply_death_cost({"class": "??", "attributes": dict(_ATTRS), "level": 5}, cost)
        assert out["attribute"] == "strength"  # highest, defensible fallback
