"""Async orchestrator joining the pure crafting resolver to DB-loaded quality tables.

The pure `async_rules.resolve_crafting` computes the spec band but cannot fetch the
per-category bonus/flaw tables (rules engine = no IO, decision f6f3cf1d23f4). This module
is the chokepoint between the two: it loads the recipe to learn its category, fetches that
category's `quality_outcomes` row (story-002), and threads it into the resolver so an
Exceptional roll attaches a bonus_property and a Partial roll a flaw.

The async worker's crafting branch delegates here. This is also the future home for
story-006's hidden-skill-counter increment on a `failure` band.
"""

import random
from dataclasses import asdict

from async_rules import resolve_crafting
from quality_outcomes import get_quality_outcomes
from recipes import get_recipe


async def resolve_crafting_outcome(activity: dict, player_data: dict, *, rng: random.Random | None = None) -> dict:
    """Resolve a crafting activity to an outcome dict, with quality tables threaded in.

    Fetches the recipe's category and that category's quality_outcomes row, then calls the
    pure resolver. None-tolerant: an unknown recipe or a missing quality row yields no
    bonus/flaw rather than crashing — the band itself still resolves. workspace_access and
    crafting_tier stay fail-loud in resolve_crafting (a miswired producer must surface).
    """
    parameters = activity.get("parameters", {})
    recipe = await get_recipe(parameters.get("recipe_id", ""))
    quality_tables = await get_quality_outcomes(recipe["category"]) if recipe else None
    outcome = resolve_crafting(
        player_data,
        parameters,
        workspace_access=parameters.get("workspace_access"),
        crafting_tier=parameters.get("crafting_tier"),
        quality_tables=quality_tables,
        rng=rng,
    )
    return asdict(outcome)
