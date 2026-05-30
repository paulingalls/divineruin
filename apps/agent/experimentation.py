"""Pure experimentation rules (M5.3): craft without a known recipe.

A player proposes a material set + an intended output. If an (unknown) recipe produces
that output from those materials, a crafting check at base_dc+4 decides success. These
functions are pure (no IO); the experiment_with_materials tool (experimentation_tools.py)
does the DB work and calls them. resolve_experimentation rolls inline like
async_rules.resolve_crafting rather than reaching for a private cross-module helper.
"""

import random
from dataclasses import dataclass

from recipe_validation import check_material_requirements
from rules_engine import skill_modifier

# Experimentation adds +4 to the recipe's normal crafting DC (spec §Experimentation Flow).
EXPERIMENTATION_DC_PENALTY = 4


@dataclass(frozen=True)
class ExperimentationOutcome:
    success: bool
    roll: int
    total: int
    dc: int
    margin: int


def resolve_experimentation(
    player_data: dict, base_dc: int, *, skill: str = "arcana", rng: random.Random | None = None
) -> ExperimentationOutcome:
    """Roll d20 + crafting skill modifier vs base_dc+4. Binary success/failure.

    base_dc is the matched recipe's normal crafting_dc; experimentation is +4 harder.
    """
    r = rng or random.Random()
    d20 = r.randint(1, 20)
    mod = skill_modifier(player_data, skill)
    total = d20 + mod
    dc = base_dc + EXPERIMENTATION_DC_PENALTY
    margin = total - dc
    return ExperimentationOutcome(success=margin >= 0, roll=d20, total=total, dc=dc, margin=margin)


def find_matching_recipe(
    recipes: list[dict],
    intended_output: str,
    provided: dict[str, int],
    catalog: dict[str, dict],
    *,
    exclude_ids: frozenset[str] = frozenset(),
) -> dict | None:
    """Return the first recipe producing intended_output whose materials are satisfiable
    from `provided`, or None. Does NOT filter by what the player knows — the caller checks
    known-vs-unknown (a known match is "just craft it", an unknown match is experimentable).

    `exclude_ids` skips those recipe ids, so the caller can search for an UNKNOWN match
    first (excluding known recipes) before falling back to detect an already-known match.
    """
    for recipe in recipes:
        if recipe["id"] in exclude_ids:
            continue
        if recipe["output_item"] != intended_output:
            continue
        if check_material_requirements(recipe["materials"], provided, catalog).satisfied:
            return recipe
    return None


def make_combination_key(materials: dict[str, int]) -> str:
    """Canonical, order-independent key for a material set: sorted 'id:qty' joined by '|'.

    Used to dedup no-match experiments in player_failed_experiments so the same fruitless
    combination isn't retried.
    """
    return "|".join(f"{mid}:{qty}" for mid, qty in sorted(materials.items()))
