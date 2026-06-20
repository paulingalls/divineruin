"""Resurrection: cost application + 4-tier anchors (M4.4 story-003).

Pure pieces of the core resurrection loop: attribute selectors that resolve a DeathCost's
attribute_target (lowest/primary/highest) to a concrete attribute, apply_death_cost which turns a
DeathCost into the persistence deltas, and resolve_resurrection_anchor's 4-tier hierarchy. The
orchestration (trigger_character_death) and real-PG round-trip live alongside / in the persistence
suite. Spec: docs/game_mechanics/game_mechanics_combat.md §The Cost Engine + §Resurrection Location."""

from unittest.mock import AsyncMock

import pytest

from death_cost import determine_death_cost
from resurrection import (
    apply_death_cost,
    highest_attribute,
    lowest_attribute,
    resolve_resurrection_anchor,
    trigger_character_death,
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


def _player(*, level=5, maxhp_override=0, cls="warrior"):
    return {
        "player_id": "p1",
        "class": cls,
        "attributes": dict(_ATTRS),
        "level": level,
        "hp": {"current": 0, "max": 60},
        "maxhp_override": maxhp_override,
        "location_id": "battlefield_danger",
    }


def _mocks(death_count_before=0):
    death_mut = AsyncMock()
    death_mut.read_death_history = AsyncMock(return_value={"count": death_count_before, "costs": []})
    death_mut.record_death = AsyncMock()
    res_mut = AsyncMock()
    return death_mut, res_mut


class TestTriggerCharacterDeath:
    @pytest.mark.asyncio
    async def test_first_death_records_no_attribute_penalty_and_revives_at_anchor(self):
        death_mut, res_mut = _mocks(death_count_before=0)
        ctx = await trigger_character_death(
            _player(),
            _LOCATIONS,
            combat_cleared=False,
            death_mutations=death_mut,
            mutations=res_mut,
            conn=object(),
        )
        assert ctx["death_count"] == 1 and ctx["tier"] == "gentle"
        death_mut.record_death.assert_awaited_once()
        res_mut.apply_attribute_penalty.assert_not_awaited()  # gentle = no attribute cost
        # Anchor: battlefield_danger not cleared -> same-region settlement camp_r1.
        assert ctx["anchor"] == "camp_r1"
        res_mut.revive_player.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_second_death_penalizes_lowest_attribute(self):
        death_mut, res_mut = _mocks(death_count_before=1)
        ctx = await trigger_character_death(
            _player(),
            _LOCATIONS,
            combat_cleared=False,
            death_mutations=death_mut,
            mutations=res_mut,
            conn=object(),
        )
        assert ctx["death_count"] == 2 and ctx["tier"] == "moderate"
        args = res_mut.apply_attribute_penalty.call_args
        assert args.args[:3] == ("p1", "charisma", -1)  # lowest attribute

    @pytest.mark.asyncio
    async def test_death_seven_applies_maxhp_override_and_clamps_revive_to_effective_max(self):
        death_mut, res_mut = _mocks(death_count_before=6)
        ctx = await trigger_character_death(
            _player(level=10, maxhp_override=0),
            _LOCATIONS,
            combat_cleared=False,
            death_mutations=death_mut,
            mutations=res_mut,
            conn=object(),
        )
        assert ctx["death_count"] == 7 and ctx["tier"] == "devastating"
        # -1 maxHP per level at L10 = -10 override delta applied.
        assert res_mut.apply_maxhp_override_delta.call_args.args[:2] == ("p1", -10)
        # Revive HP clamped to effective max = base 60 + override -10 = 50.
        assert ctx["revive_hp"] == 50
        assert res_mut.revive_player.call_args.args[2] == 50
