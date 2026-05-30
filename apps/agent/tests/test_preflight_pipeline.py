"""Tests for the crafting pre-flight pipeline (story-003, M5.2).

Pure deterministic function — plain args, no DB. run_preflight runs the spec's
five gates (Knowledge, Skill Tier, Workspace, Materials, Tainted-Expert) in order
and reports the FIRST failure. Gate inputs are produced by story-004; here they
are passed directly.
"""

import pytest

import preflight_pipeline as pf
from recipe_validation import RECIPE_TIER_ORDER
from rules_engine import SKILL_TIER_ORDER

# materials catalog: material_id -> {category, tier} (mirrors test_recipe_validation).
CATALOG = {
    "iron_ingot": {"category": "metal", "tier": 1},
    "steel_ingot": {"category": "metal", "tier": 2},
    "oak_plank": {"category": "wood", "tier": 1},
}


def _recipe(**overrides):
    """A fully craftable recipe dict; override one field to fail a single gate."""
    recipe = {
        "id": "iron_sword",
        "tier": "trained",
        "workspace_required": "forge",
        "materials": [{"material_id": "iron_ingot", "quantity": 2, "tier_minimum": 1, "substitutable": False}],
        "tainted_materials": False,
    }
    recipe.update(overrides)
    return recipe


def _run(**overrides):
    """Call run_preflight with all-passing defaults; override to fail one gate."""
    args = {
        "recipe": _recipe(),
        "known_recipe_ids": {"iron_sword"},
        "crafting_tier": "expert",  # >= trained, and >= expert (tainted-safe)
        "accessible_workspaces": {"field", "forge"},
        "available_materials": {"iron_ingot": 2},
        "materials_catalog": CATALOG,
    }
    args.update(overrides)
    return pf.run_preflight(**args)


def test_skill_and_recipe_tier_orders_are_index_aligned():
    # Check 2 compares SKILL_TIER_ORDER.index(crafting_tier) against
    # RECIPE_TIER_ORDER.index(recipe.tier) — that only gates correctly if the two
    # lists stay positionally aligned (untrained↔basic, trained↔trained, …). This
    # pins the correspondence so reordering or extending either list fails loud
    # here rather than silently mis-gating crafting.
    assert list(zip(SKILL_TIER_ORDER, RECIPE_TIER_ORDER, strict=True)) == [
        ("untrained", "basic"),
        ("trained", "trained"),
        ("expert", "expert"),
        ("master", "master"),
    ]


class TestKnowledgeGate:
    def test_known_recipe_passes_knowledge(self):
        assert _run().passed is True

    def test_unknown_recipe_fails_knowledge(self):
        result = _run(known_recipe_ids=set())
        assert result.passed is False
        assert result.failed_check == "knowledge"
        assert result.reason


class TestSkillTierGate:
    def test_crafting_tier_equal_to_recipe_tier_passes(self):
        # trained crafter, trained recipe.
        assert _run(crafting_tier="trained").passed is True

    def test_crafting_tier_above_recipe_tier_passes(self):
        assert _run(crafting_tier="master").passed is True

    def test_crafting_tier_below_recipe_tier_fails(self):
        # untrained crafter (caps at basic) cannot craft a trained recipe.
        result = _run(crafting_tier="untrained")
        assert result.passed is False
        assert result.failed_check == "skill_tier"

    def test_untrained_can_make_basic(self):
        assert _run(recipe=_recipe(tier="basic"), crafting_tier="untrained").passed is True

    def test_unknown_crafting_tier_fails_loud(self):
        with pytest.raises(ValueError):
            _run(crafting_tier="grandmaster")

    def test_unknown_recipe_tier_fails_loud(self):
        with pytest.raises(ValueError):
            _run(recipe=_recipe(tier="legendary"))


class TestWorkspaceGate:
    def test_accessible_workspace_passes(self):
        assert _run(accessible_workspaces={"field", "forge"}).passed is True

    def test_inaccessible_workspace_fails(self):
        # Player has only field/workshop; the recipe needs a forge.
        result = _run(accessible_workspaces={"field", "workshop"})
        assert result.passed is False
        assert result.failed_check == "workspace"

    def test_lab_does_not_satisfy_a_forge_recipe(self):
        # Exact-type access, not rank >=: a laboratory is not a forge.
        result = _run(accessible_workspaces={"field", "laboratory"})
        assert result.passed is False
        assert result.failed_check == "workspace"

    def test_unknown_recipe_workspace_fails_loud(self):
        with pytest.raises(ValueError):
            _run(recipe=_recipe(workspace_required="smithy"))


class TestMaterialsGate:
    def test_sufficient_materials_pass(self):
        assert _run(available_materials={"iron_ingot": 2}).passed is True

    def test_insufficient_materials_fail(self):
        result = _run(available_materials={"iron_ingot": 1})
        assert result.passed is False
        assert result.failed_check == "materials"

    def test_substitutable_material_satisfies(self):
        # A substitutable metal req is met by a same-category, tier-sufficient sub.
        recipe = _recipe(
            materials=[{"material_id": "iron_ingot", "quantity": 2, "tier_minimum": 1, "substitutable": True}]
        )
        # No iron on hand, but 2 steel (metal, tier 2 >= 1) substitutes.
        assert _run(recipe=recipe, available_materials={"steel_ingot": 2}).passed is True


class TestGateOrdering:
    def test_knowledge_checked_before_skill_tier(self):
        # Unknown recipe AND tier too low → the FIRST failure (knowledge) wins.
        result = _run(known_recipe_ids=set(), crafting_tier="untrained")
        assert result.failed_check == "knowledge"

    def test_skill_tier_checked_before_workspace(self):
        result = _run(crafting_tier="untrained", accessible_workspaces={"field"})
        assert result.failed_check == "skill_tier"

    def test_workspace_checked_before_materials(self):
        result = _run(accessible_workspaces={"field"}, available_materials={})
        assert result.failed_check == "workspace"

    def test_materials_checked_before_tainted(self):
        # Tainted recipe + sub-Expert crafter + missing materials → materials wins
        # (Check 4 precedes Check 5).
        result = _run(
            recipe=_recipe(tainted_materials=True),
            crafting_tier="trained",
            available_materials={},
        )
        assert result.failed_check == "materials"

    def test_all_gates_fail_reports_knowledge_first(self):
        result = _run(
            known_recipe_ids=set(),
            crafting_tier="untrained",
            accessible_workspaces=set(),
            available_materials={},
            recipe=_recipe(tainted_materials=True),
        )
        assert result.failed_check == "knowledge"


class TestTaintedExpertGate:
    def test_tainted_recipe_passes_for_expert(self):
        assert _run(recipe=_recipe(tainted_materials=True), crafting_tier="expert").passed is True

    def test_tainted_recipe_passes_for_master(self):
        assert _run(recipe=_recipe(tainted_materials=True), crafting_tier="master").passed is True

    @pytest.mark.parametrize("tier", ["untrained", "trained"])
    def test_tainted_recipe_refuses_below_expert(self, tier):
        # A sub-Expert crafter cannot work tainted materials. Use a basic recipe so
        # the skill-tier gate (Check 2) passes and Check 5 is the one that fires.
        result = _run(recipe=_recipe(tier="basic", tainted_materials=True), crafting_tier=tier)
        assert result.passed is False
        assert result.failed_check == "tainted_expert"

    def test_untainted_recipe_unaffected(self):
        # A plain untainted basic recipe by an untrained crafter passes Check 5.
        assert _run(recipe=_recipe(tier="basic", tainted_materials=False), crafting_tier="untrained").passed is True
