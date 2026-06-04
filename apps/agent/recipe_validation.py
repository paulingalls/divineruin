"""Recipe acquisition validators (M5.1). Zero IO, zero async, deterministic.

Pure functions for the recipe surface: slot-capacity gating by Crafting skill
tier and material-requirement checks (substitution + tier_minimum). DB reads
happen in the calling @function_tools; these take plain args so they stay
exhaustively unit-testable. Consumed by recipe_tools._learn_recipe_impl (slot gate)
and the M5.2 three-check materials gate (check_material_requirements).
"""

from dataclasses import dataclass

# Recipe.tier vocabulary (basic|trained|expert|master) — distinct from the
# crafting SKILL tier (untrained|trained|expert|master); the overlapping words
# 'trained'/'expert' span two enums (concern 3c2fa065a7cd). Untrained crafters
# cap at 'basic'. This is genuine ordering logic, not DB data — the slot caps it
# compares against come from the recipe_slots table (see below).
RECIPE_TIER_ORDER = ["basic", "trained", "expert", "master"]


# Item rarity -> the minimum RECIPE tier required to craft it (spec Item Rarity
# and Tier, crafting.md:347-353): Rare items are Expert+ recipes, Legendary are
# Master. Common/Uncommon are unconstrained (absent here). Keyed on RECIPE_TIER_ORDER,
# not the crafting-skill vocab.
_MAGIC_MIN_RECIPE_TIER = {"rare": "expert", "legendary": "master"}


@dataclass(frozen=True)
class SlotCapacityResult:
    allowed: bool
    reason: str  # "" when allowed


@dataclass(frozen=True)
class MagicTierResult:
    allowed: bool
    reason: str  # "" when allowed


def validate_magic_item_craft_tier(output_rarity: str, recipe_tier: str) -> MagicTierResult:
    """Is `recipe_tier` high enough to craft an item of `output_rarity`?

    Spec magic-item gate: Rare items require an Expert+ recipe, Legendary require
    Master; common/uncommon are unconstrained. Pure ordering logic over
    RECIPE_TIER_ORDER (the recipe-tier vocab basic|trained|expert|master — NOT the
    crafting-skill vocab). Fails loud on an unknown rarity or recipe tier. The
    runtime player-skill refusal already rides on the preflight skill-vs-recipe_tier
    gate; this formalizes the magic rule and guards content (the content-invariant
    test joins each craftable magic item to its recipe and asserts this holds).
    """
    if recipe_tier not in RECIPE_TIER_ORDER:
        raise ValueError(f"recipe_tier {recipe_tier!r} is not a valid recipe tier")
    if output_rarity not in {"common", "uncommon", "rare", "legendary"}:
        raise ValueError(f"output_rarity {output_rarity!r} is not a valid rarity")

    min_tier = _MAGIC_MIN_RECIPE_TIER.get(output_rarity)
    if min_tier is None:
        return MagicTierResult(True, "")  # common/uncommon: no tier floor
    if RECIPE_TIER_ORDER.index(recipe_tier) < RECIPE_TIER_ORDER.index(min_tier):
        return MagicTierResult(
            False,
            f"{output_rarity} items require a {min_tier}+ recipe; {recipe_tier} is too low",
        )
    return MagicTierResult(True, "")


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


def _eligible_substitute_ids(named: str, tier_minimum: int, catalog: dict[str, dict]) -> list[str]:
    """Catalog ids that may substitute for `named`: same category, tier >= tier_minimum,
    and not the named material itself. Shared by check_material_requirements (the greedy
    gate) and allocate_materials (the disjoint consume) so the eligibility rule lives in
    one place. Unordered — callers impose any ordering they need."""
    req_category = catalog.get(named, {}).get("category")
    if req_category is None:
        return []
    return [
        cid
        for cid, meta in catalog.items()
        if cid != named and meta.get("category") == req_category and meta.get("tier", 0) >= tier_minimum
    ]


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

        # The named material always counts, plus eligible substitutes when allowed.
        candidate_ids = {material_id}
        if substitutable:
            candidate_ids.update(_eligible_substitute_ids(material_id, tier_minimum, catalog))

        on_hand = sum(available.get(cid, 0) for cid in candidate_ids)
        if on_hand < need:
            return MaterialCheckResult(
                False,
                f"need {need}x {material_id} (have {on_hand} usable)"
                + ("; substitutes below tier minimum or wrong category" if substitutable else ""),
            )
    return MaterialCheckResult(True, "")


@dataclass(frozen=True)
class MaterialAllocation:
    satisfied: bool
    reason: str  # "" when satisfied
    flat: list[str]  # allocated unit ids repeated by quantity (recipeMaterialIds shape)
    by_id: dict[str, int]  # material_id -> units to deduct


def _candidate_ids(req: dict, catalog: dict[str, dict]) -> list[str]:
    """Eligible material ids for `req`, NAMED-FIRST then substitutes of the same
    category meeting tier_minimum, ordered (tier asc, id) so the cheapest acceptable
    substitute is spent first and higher-tier materials are preserved."""
    named = req["material_id"]
    candidates = [named]
    if req["substitutable"]:
        subs = _eligible_substitute_ids(named, req["tier_minimum"], catalog)
        # cheapest acceptable substitute first (tier asc, id) so higher-tier mats are preserved.
        subs.sort(key=lambda cid: (catalog[cid].get("tier", 0), cid))
        candidates.extend(subs)
    return candidates


def allocate_materials(required: list[dict], available: dict[str, int], catalog: dict[str, dict]) -> MaterialAllocation:
    """Pick a concrete DISJOINT allocation of `available` units satisfying every
    requirement, for the craft-consume path. Unlike check_material_requirements
    (greedy per-requirement — counts shared substitutable units toward multiple
    reqs), this spends each unit once: it processes requirements most-constrained-
    first (non-substitutable before substitutable, then fewest candidate pools) so a
    flexible req can't starve a stricter one, and deducts from a working copy of
    `available`. Returns the deduction map + the flat unit list to store as the
    activity's required_materials. Unmet -> satisfied=False (resolves debt cdce6c6a776d:
    a recipe that passes the greedy pre-flight gate can still fail here when no single
    allocation covers all requirements — the caller surfaces that as a clear error).

    LIMITATION (greedy, not complete matching): most-constrained-first + named-first is
    a heuristic, not full bipartite matching. With several substitutable requirements
    over deeply overlapping pools, a fixed-priority pass can in principle consume a unit
    a later requirement uniquely needs and report unsatisfiable when a valid disjoint
    allocation exists (false negative -> a craftable recipe rejected). Sound for realistic
    recipe sizes (few requirements, small same-category pools); the failure mode degrades
    to a clear ToolError, never a silent over-consume. If recipes grow complex enough to
    hit it, replace this with a max-flow / augmenting-path matcher."""
    remaining = dict(available)
    by_id: dict[str, int] = {}
    # Most-constrained-first: False (non-substitutable) sorts before True; then fewer
    # eligible pools first. Keeps a substitutable req from eating a unit a stricter
    # req needs.
    ordered = sorted(required, key=lambda r: (r["substitutable"], len(_candidate_ids(r, catalog))))
    for req in ordered:
        need = req["quantity"]
        for cid in _candidate_ids(req, catalog):
            if need == 0:
                break
            take = min(need, remaining.get(cid, 0))
            if take > 0:
                by_id[cid] = by_id.get(cid, 0) + take
                remaining[cid] -= take
                need -= take
        if need > 0:
            return MaterialAllocation(
                False, f"cannot allocate {req['quantity']}x {req['material_id']} from inventory", [], {}
            )
    flat = [cid for cid, qty in by_id.items() for _ in range(qty)]
    return MaterialAllocation(True, "", flat, by_id)
