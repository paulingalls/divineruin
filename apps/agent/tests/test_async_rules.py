"""Tests for async activity rules engine — pure functions, deterministic with RNG."""

import random

import pytest

from async_rules import (
    resolve_companion_errand,
    resolve_crafting,
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


# --- resolve_crafting ---


def _resolve_craft(params, *, workspace_access=None, crafting_tier="expert", rng=None, player=None):
    """resolve_crafting with gate-PASSING defaults so the roll-focused tests exercise
    the d20 path. The forge recipe in PARAMS is satisfied by ["field", "forge"] access
    and an Expert (non-tainted) crafter. Gate-failure tests override these."""
    return resolve_crafting(
        player or SAMPLE_PLAYER,
        params,
        workspace_access=["field", "forge"] if workspace_access is None else workspace_access,
        crafting_tier=crafting_tier,
        rng=rng,
    )


class TestResolveCrafting:
    PARAMS = {
        "recipe_id": "iron_sword",
        "result_item_id": "iron_sword",
        "result_item_name": "Iron Sword",
        "required_materials": ["iron_ingot", "leather_strip"],
        "skill": "arcana",
        "dc": 13,
        "workspace_required": "forge",
        "tainted_materials": False,
    }

    def test_success_on_high_roll(self):
        # Find a seed that gives high roll
        for seed in range(200):
            rng = random.Random(seed)
            d20 = rng.randint(1, 20)
            if d20 == 20:
                rng = random.Random(seed)
                result = _resolve_craft(self.PARAMS, rng=rng)
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
                result = _resolve_craft(self.PARAMS, rng=rng)
                assert result.tier == "failure"
                assert result.crafted_item_id is None
                assert len(result.materials_returned) > 0
                return
        pytest.fail("Could not find seed for nat 1")

    def test_all_tiers_reachable(self):
        """Run many seeds, verify we can reach different outcome tiers."""
        tiers_seen = set()
        for seed in range(500):
            result = _resolve_craft(self.PARAMS, rng=random.Random(seed))
            tiers_seen.add(result.tier)
        # Should reach at least 3 of 4 tiers
        assert len(tiers_seen) >= 3

    def test_narrative_context_populated(self):
        result = _resolve_craft(self.PARAMS, rng=random.Random(42))
        ctx = result.narrative_context
        assert "tier" in ctx
        assert "roll" in ctx
        assert "dc" in ctx
        assert "recipe_name" in ctx
        assert ctx["npc_id"] == "grimjaw_blacksmith"

    def test_deterministic_with_rng(self):
        r1 = _resolve_craft(self.PARAMS, rng=random.Random(42))
        r2 = _resolve_craft(self.PARAMS, rng=random.Random(42))
        assert r1.tier == r2.tier
        assert r1.quality_bonus == r2.quality_bonus

    def test_decision_options_always_present(self):
        for seed in range(20):
            result = _resolve_craft(self.PARAMS, rng=random.Random(seed))
            assert len(result.decision_options) >= 2
            for opt in result.decision_options:
                assert "id" in opt
                assert "label" in opt

    # --- story-005: fail-loud on absent gate inputs ---

    def test_absent_workspace_access_raises(self):
        with pytest.raises(ValueError, match="workspace_access"):
            resolve_crafting(SAMPLE_PLAYER, self.PARAMS, crafting_tier="expert", rng=random.Random(1))

    def test_absent_crafting_tier_raises(self):
        with pytest.raises(ValueError, match="crafting_tier"):
            resolve_crafting(SAMPLE_PLAYER, self.PARAMS, workspace_access=["field", "forge"], rng=random.Random(1))

    def test_missing_workspace_required_param_raises(self):
        params = {k: v for k, v in self.PARAMS.items() if k != "workspace_required"}
        with pytest.raises(ValueError, match="workspace_required"):
            _resolve_craft(params, rng=random.Random(1))

    def test_missing_tainted_param_raises(self):
        params = {k: v for k, v in self.PARAMS.items() if k != "tainted_materials"}
        with pytest.raises(ValueError, match="tainted_materials"):
            _resolve_craft(params, rng=random.Random(1))

    # --- story-005: resolution-time gate failures (failure outcome, not a raise) ---

    def test_workspace_gate_failure_returns_failure_outcome(self):
        # Forge recipe, but the player only has field access -> gate fails.
        result = _resolve_craft(self.PARAMS, workspace_access=["field"], rng=random.Random(1))
        assert result.tier == "failure"
        assert result.crafted_item_id is None
        assert result.materials_consumed == ["iron_ingot", "leather_strip"]
        assert result.materials_returned == []
        assert result.narrative_context["gate"] == "workspace"
        assert len(result.decision_options) >= 2

    def test_tainted_gate_failure_returns_failure_outcome(self):
        params = {**self.PARAMS, "tainted_materials": True}
        # Sub-Expert crafter working tainted materials -> gate fails.
        result = _resolve_craft(params, crafting_tier="trained", rng=random.Random(1))
        assert result.tier == "failure"
        assert result.crafted_item_id is None
        assert result.materials_consumed == ["iron_ingot", "leather_strip"]
        assert result.materials_returned == []
        assert result.narrative_context["gate"] == "tainted_expert"

    def test_tainted_expert_proceeds_past_gate(self):
        # Tainted materials + Expert crafter: gate passes, the roll runs and can succeed.
        params = {**self.PARAMS, "tainted_materials": True}
        tiers_seen = set()
        for seed in range(200):
            result = _resolve_craft(params, crafting_tier="expert", rng=random.Random(seed))
            tiers_seen.add(result.tier)
        assert "success" in tiers_seen  # the roll path was reached, not gate-blocked

    def test_gate_failure_is_rng_independent(self):
        # A gate failure consumes no rng, so every seed yields the same failure outcome.
        outcomes = {
            _resolve_craft(self.PARAMS, workspace_access=["field"], rng=random.Random(seed)).tier for seed in range(50)
        }
        assert outcomes == {"failure"}


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
        for etype in ("scout", "social", "acquire", "relationship"):
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
