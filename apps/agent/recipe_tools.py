"""Recipe acquisition agent tools (story-006, M5.1).

`learn_recipe` is the mutating write surface: it locks the player row FOR UPDATE
(serializing per-player learns so the slot count→write is atomic), gates on
recipe-slot capacity (recipe_validation), and records the learn in
player_known_recipes. `query_recipe_requirements` is a read tool returning a
recipe's crafting requirements.

Errors raise LiveKit `ToolError` (ADR 0002). The `_*_impl` helpers expose
`*_mod=` keyword seams for TEST-ONLY injection; production callers use the
`@function_tool` wrappers. Recipe data comes from the DB-loaded recipes accessor
(story-005); slot caps from recipe_validation (mirrors migration 019).
"""

import json
import logging

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import db
import db_mutations
import db_queries
import recipe_slots
import recipes
from db_errors import db_tool
from recipe_validation import validate_recipe_slot_capacity
from session_data import SessionData
from tool_support import _validate_id

logger = logging.getLogger("divineruin.recipe_tools")

# player_known_recipes.learned_via acquisition tracks (migration 019 / spec §Recipe Acquisition).
LEARNED_VIA = frozenset({"training", "npc_teaching", "discovery", "experimentation", "tier_advancement"})


@function_tool()
async def learn_recipe(
    context: RunContext[SessionData],
    recipe_id: str,
    learned_via: str,
) -> str:
    """Record that the player has learned a crafting recipe. Use when an NPC
    teaches a recipe, the player finds a schematic, or otherwise acquires one.

    Args:
        recipe_id: The recipe being learned.
        learned_via: How it was acquired — one of: training, npc_teaching,
            discovery, experimentation, tier_advancement.
    """
    return await _learn_recipe_impl(context, recipe_id, learned_via)


async def _learn_recipe_impl(
    context: RunContext[SessionData],
    recipe_id: str,
    learned_via: str,
    *,
    db_mod=db,
    queries_mod=db_queries,
    mutations_mod=db_mutations,
    recipes_mod=recipes,
    slots_mod=recipe_slots,
) -> str:
    context.disallow_interruptions()
    _validate_id(recipe_id, "recipe_id")
    if learned_via not in LEARNED_VIA:
        raise ToolError(f"Invalid learned_via {learned_via!r}; expected one of {sorted(LEARNED_VIA)}.")
    player_id = context.userdata.player_id
    logger.info("learn_recipe: player=%s recipe=%s via=%s", player_id, recipe_id, learned_via)

    # Cached reference reads — done BEFORE opening the txn so they don't acquire a
    # second pooled connection while this learn holds one (pool max_size=5; a
    # nested acquire under cold-cache concurrency could exhaust the pool).
    recipe = await recipes_mod.get_recipe(recipe_id)
    if recipe is None:
        raise ToolError(f"Unknown recipe: {recipe_id}")
    slots = await slots_mod.get_recipe_slots()

    async with db_mod.transaction() as conn:
        # Lock the player row so a concurrent learn can't pass the same slot
        # check before this one's write lands (count→insert stays atomic).
        player = await queries_mod.get_player(player_id, conn=conn, for_update=True)
        if not player:
            raise ToolError(f"Unknown player: {player_id}")

        crafting_tier = (await queries_mod.get_single_skill_advancement(player_id, "crafting", conn=conn))["tier"]
        known_count = await queries_mod.count_player_known_recipes(player_id, conn=conn)

        # A missing/partial recipe_slots row for a real crafting tier is a content
        # bug; surface it as ToolError so the tool keeps its ADR-0002 error shape
        # instead of leaking a raw ValueError/KeyError to the agent.
        try:
            capacity = validate_recipe_slot_capacity(crafting_tier, known_count, recipe["tier"], slots)
        except (ValueError, KeyError) as exc:
            raise ToolError(f"Recipe slot configuration error for crafting tier {crafting_tier!r}: {exc}") from exc
        if not capacity.allowed:
            raise ToolError(capacity.reason)

        inserted = await mutations_mod.add_player_known_recipe(player_id, recipe_id, learned_via, conn=conn)
        if not inserted:
            raise ToolError(f"Player already knows recipe {recipe_id}.")

    return json.dumps(
        {
            "learned": recipe_id,
            "name": recipe["name"],
            "tier": recipe["tier"],
            "learned_via": learned_via,
            "known_count": known_count + 1,
        }
    )


@function_tool()
@db_tool
async def query_recipe_requirements(
    context: RunContext[SessionData],
    recipe_id: str,
) -> str:
    """Look up what a recipe needs to craft: required + optional materials, the
    workspace, the crafting DC, and the craft time.

    Args:
        recipe_id: The recipe to inspect.
    """
    return await _query_recipe_requirements_impl(context, recipe_id)


async def _query_recipe_requirements_impl(
    context: RunContext[SessionData],
    recipe_id: str,
    *,
    recipes_mod=recipes,
) -> str:
    _validate_id(recipe_id, "recipe_id")
    recipe = await recipes_mod.get_recipe(recipe_id)
    if recipe is None:
        raise ToolError(f"Unknown recipe: {recipe_id}")
    return json.dumps(
        {
            "recipe_id": recipe["id"],
            "name": recipe["name"],
            "tier": recipe["tier"],
            "materials": recipe["materials"],
            "optional_materials": recipe["optional_materials"],
            "workspace_required": recipe["workspace_required"],
            "crafting_dc": recipe["crafting_dc"],
            "time": recipe["time"],
        }
    )
