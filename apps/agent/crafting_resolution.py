"""Resolve crafting with catalog quality tables, then offer sale for a priced output."""

import random
from dataclasses import asdict

from async_rules import resolve_crafting
from db_content_queries import get_item
from pricing_queries import get_economy_pricing
from quality_outcomes import get_quality_outcomes
from recipes import get_recipe
from sale_pricing import quote_sale


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
    result = asdict(outcome)
    if outcome.tier == "success":
        item = await get_item(result["crafted_item_id"])
        if item is None:
            raise ValueError(f"Crafted item {result['crafted_item_id']} is missing")
        pricing = await get_economy_pricing()
        if not quote_sale(item, pricing, kind="crafted")["available"]:
            result["decision_options"] = [option for option in result["decision_options"] if option["id"] != "sell"]
    # Thread the recipe's per-band sensory cue into the narration context (decision
    # crafting-narration-ssot): narration_cues[band] is the base prose for the resolved
    # band, complementary to the per-category bonus/flaw. None-tolerant — a recipe may
    # omit exceptional/partial cues (success/failure are always present).
    if recipe:
        cue = (recipe.get("narration_cues") or {}).get(result["tier"])
        if cue:
            result["narrative_context"]["recipe_cue"] = cue
    return result
