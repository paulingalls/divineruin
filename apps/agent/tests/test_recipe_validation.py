"""Tests for recipe acquisition validators (story-006, M5.1).

Pure deterministic functions — plain args, no DB. Slot capacity mirrors the
migration-019 recipe_slots seed (Untrained=3 per decision d25e04f066a3); material
checks cover substitution + tier_minimum.
"""

import pytest

import recipe_validation as rv


class TestValidateRecipeSlotCapacity:
    def test_untrained_allows_basic_under_cap(self):
        # Untrained: cap 3, max recipe tier 'basic'.
        result = rv.validate_recipe_slot_capacity("untrained", 2, "basic")
        assert result.allowed is True
        assert result.reason == ""

    def test_untrained_rejects_at_cap(self):
        result = rv.validate_recipe_slot_capacity("untrained", 3, "basic")
        assert result.allowed is False
        assert "3" in result.reason  # cap surfaced

    def test_untrained_rejects_recipe_tier_above_max(self):
        # Untrained may only learn 'basic'; a 'trained' recipe is ineligible even with slots.
        result = rv.validate_recipe_slot_capacity("untrained", 0, "trained")
        assert result.allowed is False
        assert "trained" in result.reason

    def test_trained_cap_is_eight(self):
        assert rv.validate_recipe_slot_capacity("trained", 7, "trained").allowed is True
        assert rv.validate_recipe_slot_capacity("trained", 8, "trained").allowed is False

    def test_expert_cap_is_fifteen(self):
        assert rv.validate_recipe_slot_capacity("expert", 14, "expert").allowed is True
        assert rv.validate_recipe_slot_capacity("expert", 15, "expert").allowed is False

    def test_master_is_unlimited(self):
        # Master cap is null in the seed — never rejected on capacity.
        assert rv.validate_recipe_slot_capacity("master", 9999, "master").allowed is True

    def test_higher_crafting_tier_may_learn_lower_recipe_tier(self):
        assert rv.validate_recipe_slot_capacity("expert", 0, "basic").allowed is True

    def test_rejects_unknown_crafting_tier(self):
        with pytest.raises(ValueError, match="crafting_tier"):
            rv.validate_recipe_slot_capacity("grandmaster", 0, "basic")

    def test_rejects_unknown_recipe_tier(self):
        with pytest.raises(ValueError, match="recipe_tier"):
            rv.validate_recipe_slot_capacity("expert", 0, "legendary")


# catalog: material_id -> {category, tier}
CATALOG = {
    "iron_ingot": {"category": "metal", "tier": 1},
    "steel_ingot": {"category": "metal", "tier": 2},
    "tin_ingot": {"category": "metal", "tier": 1},
    "oak_plank": {"category": "wood", "tier": 1},
}


def _req(material_id, quantity, tier_minimum, substitutable):
    return {
        "material_id": material_id,
        "quantity": quantity,
        "tier_minimum": tier_minimum,
        "substitutable": substitutable,
    }


class TestCheckMaterialRequirements:
    def test_exact_material_sufficient_quantity_satisfies(self):
        required = [_req("iron_ingot", 2, 1, False)]
        result = rv.check_material_requirements(required, {"iron_ingot": 2}, CATALOG)
        assert result.satisfied is True

    def test_insufficient_exact_quantity_unmet(self):
        required = [_req("iron_ingot", 3, 1, False)]
        result = rv.check_material_requirements(required, {"iron_ingot": 2}, CATALOG)
        assert result.satisfied is False
        assert "iron_ingot" in result.reason

    def test_non_substitutable_does_not_use_other_materials(self):
        required = [_req("iron_ingot", 2, 1, False)]
        # Has plenty of a same-category material, but req is not substitutable.
        result = rv.check_material_requirements(required, {"steel_ingot": 5}, CATALOG)
        assert result.satisfied is False

    def test_substitute_same_category_meeting_tier_floor_resolves(self):
        # iron_ingot required but substitutable; steel_ingot (metal, tier 2 >= 1) substitutes.
        required = [_req("iron_ingot", 2, 1, True)]
        result = rv.check_material_requirements(required, {"steel_ingot": 2}, CATALOG)
        assert result.satisfied is True

    def test_substitute_below_tier_minimum_rejected(self):
        # tin_ingot is metal tier 1 but tier_minimum is 2 -> rejected as substitute.
        required = [_req("steel_ingot", 1, 2, True)]
        result = rv.check_material_requirements(required, {"tin_ingot": 5}, CATALOG)
        assert result.satisfied is False
        assert "steel_ingot" in result.reason

    def test_substitute_wrong_category_rejected(self):
        # oak_plank is wood, cannot substitute for a metal requirement.
        required = [_req("iron_ingot", 1, 1, True)]
        result = rv.check_material_requirements(required, {"oak_plank": 5}, CATALOG)
        assert result.satisfied is False

    def test_all_requirements_must_be_met(self):
        required = [_req("iron_ingot", 1, 1, False), _req("oak_plank", 1, 1, False)]
        result = rv.check_material_requirements(required, {"iron_ingot": 1}, CATALOG)
        assert result.satisfied is False
        assert "oak_plank" in result.reason

    def test_empty_requirements_satisfied(self):
        result = rv.check_material_requirements([], {}, CATALOG)
        assert result.satisfied is True
