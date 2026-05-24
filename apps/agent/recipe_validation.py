"""Recipe acquisition validators (M5.1). Zero IO, zero async, deterministic.

Pure functions for the recipe surface: slot-capacity gating by Crafting skill
tier and material-requirement checks (substitution + tier_minimum). DB reads
happen in the calling @function_tools; these take plain args so they stay
exhaustively unit-testable. Consumed by recipe_tools.learn_recipe (slot gate)
and the M5.2 three-check materials gate (check_material_requirements).
"""

from dataclasses import dataclass

# Recipe.tier vocabulary (basic|trained|expert|master) — distinct from the
# crafting SKILL tier (untrained|trained|expert|master); the overlapping words
# 'trained'/'expert' span two enums (concern 3c2fa065a7cd). Untrained crafters
# cap at 'basic'. This is genuine ordering logic, not DB data — the slot caps it
# compares against come from the recipe_slots table (see below).
RECIPE_TIER_ORDER = ["basic", "trained", "expert", "master"]


@dataclass(frozen=True)
class SlotCapacityResult:
    allowed: bool
    reason: str  # "" when allowed


@dataclass(frozen=True)
class MaterialCheckResult:
    satisfied: bool
    reason: str  # "" when satisfied


def validate_recipe_slot_capacity(
    crafting_tier: str, known_count: int, recipe_tier: str, slots: dict[str, dict]
) -> SlotCapacityResult:
    """Can a crafter at `crafting_tier` holding `known_count` recipes learn one of
    `recipe_tier`? Enforces both tier-eligibility (recipe_tier <= the tier's max)
    and capacity (known_count < the tier's slot cap; Master = unlimited).

    `slots` is the recipe_slots reference data, loaded from the DB by the caller
    (recipe_slots.get_recipe_slots): crafting_tier -> {"max_recipe_tier": str,
    "known_recipe_slots": int | None}. Passing it in keeps this function pure and
    keeps the caps in one place (the DB), mirroring how check_material_requirements
    takes its catalog arg — no second hardcoded copy lives here (concern d125d022f084).
    """
    if crafting_tier not in slots:
        raise ValueError(f"crafting_tier {crafting_tier!r} is not a valid crafting tier")
    if recipe_tier not in RECIPE_TIER_ORDER:
        raise ValueError(f"recipe_tier {recipe_tier!r} is not a valid recipe tier")

    max_tier = slots[crafting_tier]["max_recipe_tier"]
    if RECIPE_TIER_ORDER.index(recipe_tier) > RECIPE_TIER_ORDER.index(max_tier):
        return SlotCapacityResult(
            False,
            f"{crafting_tier} crafters can learn up to {max_tier} recipes; {recipe_tier} is too advanced",
        )

    cap = slots[crafting_tier]["known_recipe_slots"]
    if cap is not None and known_count >= cap:
        return SlotCapacityResult(False, f"recipe slots full: {known_count}/{cap} for {crafting_tier} crafters")
    return SlotCapacityResult(True, "")


def check_material_requirements(
    required: list[dict], available: dict[str, int], catalog: dict[str, dict]
) -> MaterialCheckResult:
    """Are a recipe's material requirements satisfiable from `available`?

    `required`: MaterialReq dicts (material_id, quantity, tier_minimum, substitutable).
    `available`: material_id -> quantity on hand.
    `catalog`: material_id -> {"category": str, "tier": int} (from materials_catalog).

    The named material always counts toward its requirement. When `substitutable`,
    any catalog material of the SAME category with tier >= tier_minimum also counts
    (a candidate below tier_minimum is rejected). Quantities sum across the named
    material plus accepted substitutes. Returns the first unmet requirement's reason.

    LIMITATION (greedy, per-requirement): each requirement is checked independently
    against the FULL `available` pool — no cross-requirement allocation. When two
    requirements draw from an overlapping substitutable pool (e.g. iron_ingot and
    steel_ingot both 'metal'), the same units are counted toward both and this may
    report satisfiable when no single allocation satisfies all requirements at once.
    Sound for the single-substitute AC2 surface; the M5.2 craft-consume path owns
    the real allocate-then-deduct pass (debt 55d8dcd38fc0).
    """
    for req in required:
        material_id = req["material_id"]
        need = req["quantity"]
        tier_minimum = req["tier_minimum"]
        substitutable = req["substitutable"]

        # The named material always counts.
        candidate_ids = {material_id}
        if substitutable:
            req_category = catalog.get(material_id, {}).get("category")
            if req_category is not None:
                for cat_id, meta in catalog.items():
                    if (
                        cat_id != material_id
                        and meta.get("category") == req_category
                        and meta.get("tier", 0) >= tier_minimum
                    ):
                        candidate_ids.add(cat_id)

        on_hand = sum(available.get(cid, 0) for cid in candidate_ids)
        if on_hand < need:
            return MaterialCheckResult(
                False,
                f"need {need}x {material_id} (have {on_hand} usable)"
                + ("; substitutes below tier minimum or wrong category" if substitutable else ""),
            )
    return MaterialCheckResult(True, "")
