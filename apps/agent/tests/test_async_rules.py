"""Tests for async activity rules engine — pure functions, deterministic with RNG."""

import random
from datetime import UTC, datetime

import pytest

from async_rules import (
    MAX_CONCURRENT_ACTIVITIES,
    VALID_ACTIVITY_TYPES,
    VALID_ERRAND_TYPES,
    compute_resolve_time,
    resolve_companion_errand,
    resolve_crafting,
    validate_activity_params,
)

SAMPLE_PLAYER = {
    "level": 3,
    "attributes": {
        "strength": 14,
        "dexterity": 12,
        "constitution": 13,
        "intelligence": 10,
        "wisdom": 11,
        "charisma": 8,
    },
    "proficiencies": ["athletics", "arcana", "perception"],
    "inventory": [
        {"id": "iron_ingot", "name": "Iron Ingot"},
        {"id": "leather_strip", "name": "Leather Strip"},
    ],
}

SAMPLE_COMPANION = {
    "id": "companion_kael",
    "name": "Kael",
    "relationship_tier": 2,
    "attributes": {
        "strength": 15,
        "dexterity": 13,
        "constitution": 14,
        "intelligence": 10,
        "wisdom": 12,
        "charisma": 11,
    },
}


# --- compute_resolve_time ---


class TestComputeResolveTime:
    def test_within_range(self):
        start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        for seed in range(20):
            rng = random.Random(seed)
            result = compute_resolve_time(3600, 7200, start_time=start, rng=rng)
            delta = (result - start).total_seconds()
            assert 3600 <= delta <= 7200

    def test_deterministic_with_rng(self):
        start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        t1 = compute_resolve_time(3600, 7200, start_time=start, rng=random.Random(42))
        t2 = compute_resolve_time(3600, 7200, start_time=start, rng=random.Random(42))
        assert t1 == t2

    def test_variance_in_soft_timer(self):
        """10 activities with 4-8 hour range should have variance."""
        start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        min_s, max_s = 14400, 28800  # 4-8 hours
        times = []
        for seed in range(10):
            rng = random.Random(seed)
            t = compute_resolve_time(min_s, max_s, start_time=start, rng=rng)
            times.append((t - start).total_seconds())

        assert all(min_s <= t <= max_s for t in times)
        # Verify actual variance — not all identical
        assert len(set(times)) > 1
        assert min(times) != max(times)

    def test_uses_current_time_if_no_start(self):
        before = datetime.now(UTC)
        result = compute_resolve_time(60, 120, rng=random.Random(1))
        assert result > before


# --- validate_activity_params ---


class TestValidateActivityParams:
    def test_valid_crafting(self):
        params = {
            "recipe_id": "iron_sword",
            "required_materials": ["iron_ingot", "leather_strip"],
        }
        result = validate_activity_params("crafting", params, SAMPLE_PLAYER, 0)
        assert result.valid is True
        assert result.errors == []

    def test_invalid_activity_type(self):
        result = validate_activity_params("fishing", {}, SAMPLE_PLAYER, 0)
        assert result.valid is False
        assert any("Invalid activity type" in e for e in result.errors)

    def test_max_concurrent_exceeded(self):
        params = {"recipe_id": "iron_sword"}
        result = validate_activity_params("crafting", params, SAMPLE_PLAYER, MAX_CONCURRENT_ACTIVITIES)
        assert result.valid is False
        assert any("concurrent" in e.lower() for e in result.errors)

    def test_crafting_missing_recipe(self):
        result = validate_activity_params("crafting", {}, SAMPLE_PLAYER, 0)
        assert result.valid is False
        assert any("recipe_id" in e for e in result.errors)

    def test_crafting_missing_materials(self):
        params = {
            "recipe_id": "iron_sword",
            "required_materials": ["iron_ingot", "mithril_dust"],
        }
        result = validate_activity_params("crafting", params, SAMPLE_PLAYER, 0)
        assert result.valid is False
        assert any("mithril_dust" in e for e in result.errors)

    def test_companion_errand_valid(self):
        params = {"errand_type": "scout", "destination": "millhaven"}
        result = validate_activity_params("companion_errand", params, SAMPLE_PLAYER, 0)
        assert result.valid is True

    def test_companion_errand_invalid_type(self):
        params = {"errand_type": "steal", "destination": "millhaven"}
        result = validate_activity_params("companion_errand", params, SAMPLE_PLAYER, 0)
        assert result.valid is False
        assert any("errand type" in e.lower() for e in result.errors)

    def test_companion_errand_missing_destination(self):
        params = {"errand_type": "scout"}
        result = validate_activity_params("companion_errand", params, SAMPLE_PLAYER, 0)
        assert result.valid is False
        assert any("destination" in e for e in result.errors)

    def test_all_valid_types_accepted(self):
        for atype in VALID_ACTIVITY_TYPES:
            if atype == "crafting":
                params = {"recipe_id": "x", "required_materials": []}
            else:
                params = {"errand_type": "scout", "destination": "x"}
            result = validate_activity_params(atype, params, SAMPLE_PLAYER, 0)
            assert result.valid is True, f"{atype} should be valid"


# --- resolve_crafting ---


class TestResolveCrafting:
    PARAMS = {
        "recipe_id": "iron_sword",
        "result_item_id": "iron_sword",
        "result_item_name": "Iron Sword",
        "required_materials": ["iron_ingot", "leather_strip"],
        "skill": "arcana",
        "dc": 13,
    }

    def test_success_on_high_roll(self):
        # Find a seed that gives high roll
        for seed in range(200):
            rng = random.Random(seed)
            d20 = rng.randint(1, 20)
            if d20 == 20:
                rng = random.Random(seed)
                result = resolve_crafting(SAMPLE_PLAYER, self.PARAMS, rng=rng)
                assert result.tier == "success"
                assert result.crafted_item_id == "iron_sword"
                assert result.crafted_item_name == "Iron Sword"
                assert result.materials_consumed == ["iron_ingot", "leather_strip"]
                assert len(result.decision_options) > 0
                return
        pytest.fail("Could not find seed for success")

    def test_failure_on_nat_1(self):
        for seed in range(200):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 1:
                rng = random.Random(seed)
                result = resolve_crafting(SAMPLE_PLAYER, self.PARAMS, rng=rng)
                assert result.tier == "failure"
                assert result.crafted_item_id is None
                assert len(result.materials_returned) > 0
                return
        pytest.fail("Could not find seed for nat 1")

    def test_all_tiers_reachable(self):
        """Run many seeds, verify we can reach different outcome tiers."""
        tiers_seen = set()
        for seed in range(500):
            rng = random.Random(seed)
            result = resolve_crafting(SAMPLE_PLAYER, self.PARAMS, rng=rng)
            tiers_seen.add(result.tier)
        # Should reach at least 3 of 4 tiers
        assert len(tiers_seen) >= 3

    def test_narrative_context_populated(self):
        rng = random.Random(42)
        result = resolve_crafting(SAMPLE_PLAYER, self.PARAMS, rng=rng)
        ctx = result.narrative_context
        assert "tier" in ctx
        assert "roll" in ctx
        assert "dc" in ctx
        assert "recipe_name" in ctx
        assert ctx["npc_id"] == "grimjaw_blacksmith"

    def test_deterministic_with_rng(self):
        r1 = resolve_crafting(SAMPLE_PLAYER, self.PARAMS, rng=random.Random(42))
        r2 = resolve_crafting(SAMPLE_PLAYER, self.PARAMS, rng=random.Random(42))
        assert r1.tier == r2.tier
        assert r1.quality_bonus == r2.quality_bonus

    def test_decision_options_always_present(self):
        for seed in range(20):
            result = resolve_crafting(SAMPLE_PLAYER, self.PARAMS, rng=random.Random(seed))
            assert len(result.decision_options) >= 2
            for opt in result.decision_options:
                assert "id" in opt
                assert "label" in opt


# --- resolve_companion_errand ---


class TestResolveCompanionErrand:
    PARAMS = {
        "errand_type": "scout",
        "destination": "millhaven",
        "dc": 12,
        "success_info": ["Found tracks leading north"],
        "great_success_info": ["Discovered a hidden path to the ruins"],
    }

    def test_success_with_good_roll(self):
        for seed in range(200):
            rng = random.Random(seed)
            result = resolve_companion_errand(SAMPLE_COMPANION, self.PARAMS, rng=rng)
            if result.tier == "success":
                assert result.errand_type == "scout"
                assert len(result.information_gained) > 0
                return
        pytest.fail("Could not find seed for success")

    def test_relationship_tier_bonus(self):
        """Higher relationship tier should produce generally better results."""
        low_rel = {**SAMPLE_COMPANION, "relationship_tier": 1}
        high_rel = {**SAMPLE_COMPANION, "relationship_tier": 4}
        low_totals = []
        high_totals = []
        for seed in range(100):
            r1 = resolve_companion_errand(low_rel, self.PARAMS, rng=random.Random(seed))
            r2 = resolve_companion_errand(high_rel, self.PARAMS, rng=random.Random(seed))
            low_totals.append(r1.narrative_context["total"])
            high_totals.append(r2.narrative_context["total"])
        # High relationship should consistently score higher
        assert sum(high_totals) > sum(low_totals)

    def test_all_errand_types(self):
        for etype in VALID_ERRAND_TYPES:
            params = {**self.PARAMS, "errand_type": etype}
            result = resolve_companion_errand(SAMPLE_COMPANION, params, rng=random.Random(42))
            assert result.errand_type == etype

    def test_complication_has_negative_relationship(self):
        for seed in range(500):
            result = resolve_companion_errand(SAMPLE_COMPANION, self.PARAMS, rng=random.Random(seed))
            if result.tier == "complication":
                assert result.relationship_change < 0
                return
        pytest.fail("Could not find seed for complication")

    def test_great_success_has_positive_relationship(self):
        for seed in range(500):
            result = resolve_companion_errand(SAMPLE_COMPANION, self.PARAMS, rng=random.Random(seed))
            if result.tier == "great_success":
                assert result.relationship_change > 0
                return
        pytest.fail("Could not find seed for great_success")

    def test_narrative_context_has_companion_info(self):
        result = resolve_companion_errand(SAMPLE_COMPANION, self.PARAMS, rng=random.Random(42))
        ctx = result.narrative_context
        assert ctx["companion_name"] == "Kael"
        assert ctx["destination"] == "millhaven"
        assert ctx["errand_type"] == "scout"

    def test_decision_options_present(self):
        for seed in range(20):
            result = resolve_companion_errand(SAMPLE_COMPANION, self.PARAMS, rng=random.Random(seed))
            assert len(result.decision_options) >= 2
