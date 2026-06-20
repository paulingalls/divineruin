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
    resolve_resurrection_anchor,
)

# Fixture location map (id -> data), exercising each anchor tier.
_LOCATIONS = {
    "battlefield_safe": {"region": "r1", "danger_level": 0},
    "battlefield_danger": {"region": "r1", "danger_level": 3},
    "camp_r1": {"region": "r1", "settlement_tier": "village", "danger_level": 1},
    "city_r2": {"region": "r2", "settlement_tier": "city", "danger_level": 0},
    "wild_r3": {"region": "r3", "danger_level": 3},
    "accord_market_square": {"region": "r9", "settlement_tier": "city", "danger_level": 0, "tags": ["starting_area"]},
}

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


class TestResolveResurrectionAnchor:
    def test_tier1_cleared_safe_battlefield_is_the_death_site(self):
        anchor = resolve_resurrection_anchor("battlefield_safe", _LOCATIONS, {}, combat_cleared=True)
        assert anchor == "battlefield_safe"

    def test_tier1_skipped_when_battlefield_still_dangerous(self):
        # combat cleared but the area is still hostile -> fall to a settlement, not the death site.
        anchor = resolve_resurrection_anchor("battlefield_danger", _LOCATIONS, {}, combat_cleared=True)
        assert anchor == "camp_r1"

    def test_tier1_skipped_when_combat_not_cleared(self):
        anchor = resolve_resurrection_anchor("battlefield_safe", _LOCATIONS, {}, combat_cleared=False)
        assert anchor == "camp_r1"  # same-region settlement

    def test_tier2_nearest_same_region_settlement(self):
        anchor = resolve_resurrection_anchor("battlefield_danger", _LOCATIONS, {}, combat_cleared=False)
        assert anchor == "camp_r1"  # r1 settlement; city_r2 is a different region

    def test_tier3_last_rested_settlement_when_no_same_region_settlement(self):
        # Death in r3 (no settlement there); fall to the player's last-rested settlement.
        player = {"last_rested_settlement_id": "city_r2"}
        anchor = resolve_resurrection_anchor("wild_r3", _LOCATIONS, player, combat_cleared=False)
        assert anchor == "city_r2"

    def test_tier4_starter_zone_fallback_when_tier3_dormant(self):
        # Tier-3 is dormant (no last-rested tracking caller yet) -> must fall through to the
        # starting_area-tagged zone. This is the live fall-through the plan-review flagged.
        anchor = resolve_resurrection_anchor("wild_r3", _LOCATIONS, {}, combat_cleared=False)
        assert anchor == "accord_market_square"
