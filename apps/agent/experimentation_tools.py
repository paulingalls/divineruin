"""Experimentation agent tool (story-004, M5.3).

`experiment_with_materials` lets the player craft WITHOUT a known recipe: they commit a
material set toward an intended output, and a crafting check at the recipe's normal DC +4
decides success. It resolves IMMEDIATELY (decision experimentation-immediate) — unlike
start_crafting_project's async wait-window — because it's the interactive "I try mixing
these" moment. Mutating-tool conventions mirror recipe_tools/crafting_tools: FOR-UPDATE
player lock, materials spent via the shared allocate→consume chain, ToolError (ADR 0002).

Outcomes:
- match + roll success → produce the item AND learn the recipe (learned_via=experimentation).
- match + roll failure → materials spent, nothing learned; RETRYABLE (not recorded).
- no match (no recipe makes the output from these materials) → materials spent, the combo
  recorded in player_failed_experiments so it isn't fruitlessly retried (short-circuits
  next time WITHOUT consuming). Decision experimentation-dedup-no-match-only.
"""

import json
import logging

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import db
import db_mutations
import db_queries
import experimentation
import experimentation_db
import materials as materials_module
import recipe_validation
import recipes
from session_data import SessionData
from tool_support import _validate_id

logger = logging.getLogger("divineruin.experimentation_tools")


@function_tool()
async def experiment_with_materials(
    context: RunContext[SessionData],
    material_ids: list[str],
    quantities: list[int],
    intended_output: str,
) -> str:
    """Attempt to craft something WITHOUT a known recipe by combining materials toward an
    intended result. Rolls a crafting check at the would-be recipe's DC + 4. On success the
    item is created and the recipe is learned permanently; on failure the materials are
    spent. Use when the player improvises ("I try mixing these to make X") rather than
    crafting a recipe they already know.

    Args:
        material_ids: The material ids the player commits to the attempt.
        quantities: Quantities, positionally aligned with material_ids (same length).
        intended_output: The item id the player hopes to create.
    """
    if len(material_ids) != len(quantities):
        raise ToolError("material_ids and quantities must have the same length.")
    if len(set(material_ids)) != len(material_ids):
        raise ToolError("material_ids must not contain duplicates.")
    materials = dict(zip(material_ids, quantities, strict=True))
    return await _experiment_with_materials_impl(context, materials, intended_output)


async def _experiment_with_materials_impl(
    context: RunContext[SessionData],
    materials: dict[str, int],
    intended_output: str,
    *,
    db_mod=db,
    queries_mod=db_queries,
    mutations_mod=db_mutations,
    recipes_mod=recipes,
    materials_mod=materials_module,
    validation_mod=recipe_validation,
    exp_db_mod=experimentation_db,
    rng=None,
) -> str:
    context.disallow_interruptions()
    _validate_id(intended_output, "intended_output")
    if not materials or not all(isinstance(q, int) and not isinstance(q, bool) and q > 0 for q in materials.values()):
        raise ToolError("Provide a non-empty map of material_id -> positive quantity.")
    # Material ids are player/LLM-supplied and flow into consume + the dedup record on the
    # no-match path, so validate them like intended_output (sibling tools only ever consume
    # recipe-sourced ids; this is the one untrusted-id surface).
    for mid in materials:
        _validate_id(mid, "material_id")
    player_id = context.userdata.player_id
    logger.info("experiment_with_materials: player=%s output=%s", player_id, intended_output)

    # Cached reference reads BEFORE the txn (pool-exhaustion guard, like _learn_recipe_impl).
    all_recipes = await recipes_mod.list_recipes()
    catalog = await materials_mod.get_materials_catalog()
    combo_key = experimentation.make_combination_key(materials)

    async with db_mod.transaction() as conn:
        player = await queries_mod.get_player(player_id, conn=conn, for_update=True)
        if not player:
            raise ToolError(f"Unknown player: {player_id}")
        available = await queries_mod.get_player_materials(player_id, conn=conn, for_update=True)
        known = frozenset(await queries_mod.get_player_known_recipe_ids(player_id, conn=conn))

        # Prefer an UNKNOWN recipe the player can legitimately discover (so a known recipe
        # sharing the output doesn't shadow a distinct unknown one).
        match = experimentation.find_matching_recipe(
            all_recipes, intended_output, materials, catalog, exclude_ids=known
        )

        if match is None and any(r["output_item"] == intended_output and r["id"] in known for r in all_recipes):
            # No unknown recipe is experimentable, but the player ALREADY KNOWS a recipe for
            # this output (whether or not the offered materials satisfy it) — that's "craft it
            # with the right materials", never a fruitless experiment. Don't consume or record.
            raise ToolError(f"You already know how to make {intended_output}; just craft it with the right materials.")

        if match is not None:
            alloc = validation_mod.allocate_materials(match["materials"], available, catalog)
            if not alloc.satisfied:
                raise ToolError(f"You can't spare the materials for that: {alloc.reason}")
            await mutations_mod.consume_player_materials(player_id, alloc.by_id, conn=conn)
            outcome = experimentation.resolve_experimentation(player, match["crafting_dc"], rng=rng)
            if outcome.success:
                await mutations_mod.add_player_known_recipe(player_id, match["id"], "experimentation", conn=conn)
                return json.dumps(
                    {
                        "outcome": "success",
                        "learned_recipe": match["id"],
                        "produced_item": match["output_item"],
                        "roll": outcome.roll,
                        "dc": outcome.dc,
                    }
                )
            return json.dumps(
                {
                    "outcome": "failure",
                    "learned_recipe": None,
                    "retryable": True,
                    "roll": outcome.roll,
                    "dc": outcome.dc,
                }
            )

        # No recipe makes intended_output from these materials.
        if await exp_db_mod.has_failed_experiment(player_id, intended_output, combo_key, conn=conn):
            return json.dumps({"outcome": "already_tried", "learned_recipe": None, "consumed": False})
        short = {mid: qty for mid, qty in materials.items() if available.get(mid, 0) < qty}
        if short:
            raise ToolError("You don't have the materials you described.")
        await mutations_mod.consume_player_materials(player_id, materials, conn=conn)
        await exp_db_mod.record_failed_experiment(player_id, intended_output, combo_key, conn=conn)
        return json.dumps({"outcome": "no_match", "learned_recipe": None, "consumed": True})
