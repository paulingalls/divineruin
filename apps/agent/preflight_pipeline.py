"""Crafting pre-flight pipeline (M5.2). Zero IO, zero async, deterministic.

The single gate for ALL crafting (the agent tool path in story-004 and, mirrored,
the server REST path in story-006). run_preflight runs the spec's five gates in
order (game_mechanics_crafting.md §Resolution Flow) and returns the FIRST failure;
only if all pass does the caller roll d20+mod vs the recipe DC.

Pure: every gate input is a plain arg, produced by the calling tool (known recipes,
crafting tier, accessible workspaces, material holdings, materials catalog). Reuses
the canonical tier orders + check_material_requirements rather than re-deriving them.
"""

from dataclasses import dataclass

from crafting_gates import tainted_blocks_crafter, workspace_accessible
from recipe_validation import RECIPE_TIER_ORDER, check_material_requirements
from rules_engine import SKILL_TIER_ORDER


@dataclass(frozen=True)
class PreflightResult:
    passed: bool
    failed_check: str | None  # stable gate slug when failed, None when passed
    reason: str  # "" when passed


def run_preflight(
    recipe: dict,
    known_recipe_ids: set[str],
    crafting_tier: str,
    accessible_workspaces: set[str],
    available_materials: dict[str, int],
    materials_catalog: dict[str, dict],
) -> PreflightResult:
    """Run the five crafting gates in order; return the first failure (or pass).

    `recipe` is a parsed recipe dict (recipes.get_recipe): id, tier,
    workspace_required, materials, tainted_materials. Tier strings fail loud
    (ValueError) if unknown — a miswired tier must not silently mis-gate.
    """
    # Check 1: Knowledge — the crafter must know the recipe.
    if recipe["id"] not in known_recipe_ids:
        return PreflightResult(False, "knowledge", f"recipe {recipe['id']} is not known")

    # Check 2: Skill Tier — crafting tier must reach the recipe's tier. SKILL and
    # RECIPE tier orders are index-aligned (untrained↔basic, trained↔trained, …),
    # so the skill index must be >= the recipe-tier index. Slot caps (recipe_slots)
    # gate LEARNING, not crafting, so they are not consulted here.
    if crafting_tier not in SKILL_TIER_ORDER:
        raise ValueError(f"crafting_tier {crafting_tier!r} is not a valid crafting tier")
    recipe_tier = recipe["tier"]
    if recipe_tier not in RECIPE_TIER_ORDER:
        raise ValueError(f"recipe tier {recipe_tier!r} is not a valid recipe tier")
    if SKILL_TIER_ORDER.index(crafting_tier) < RECIPE_TIER_ORDER.index(recipe_tier):
        return PreflightResult(False, "skill_tier", f"{crafting_tier} crafting cannot make a {recipe_tier} recipe")

    # Check 3: Workspace — the recipe's required workspace must be accessible.
    # Exact-type access, NOT rank >= — a laboratory must not satisfy a forge recipe
    # (workspace-check3-access). Unknown workspace fails loud inside the predicate.
    if not workspace_accessible(recipe["workspace_required"], accessible_workspaces):
        return PreflightResult(False, "workspace", f"no access to a {recipe['workspace_required']} workspace")

    # Check 4: Materials — the recipe's requirements must be satisfiable from the
    # player's holdings (reuses the M5.1 substitution-aware primitive).
    material_check = check_material_requirements(recipe["materials"], available_materials, materials_catalog)
    if not material_check.satisfied:
        return PreflightResult(False, "materials", material_check.reason)

    # Check 5: Tainted-Expert — working tainted (Hollow-touched) materials requires
    # at least Expert crafting; a lesser crafter is refused (spec Resolution Flow).
    if tainted_blocks_crafter(crafting_tier, recipe["tainted_materials"]):
        return PreflightResult(
            False, "tainted_expert", f"{crafting_tier} crafting cannot safely work tainted materials"
        )

    return PreflightResult(True, None, "")
