"""World query tools for the DM agent."""

import json
import logging
import random
from typing import Literal

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import db_content_queries
import db_queries
from db_errors import db_tool
from session_data import SessionData
from settlement_generation import generate_settlement_npcs
from tool_support import (
    _location_for_narration,
    _npc_for_narration,
    _validate_id,
    apply_time_conditions,
    filter_knowledge,
)

logger = logging.getLogger("divineruin.tools")


async def _resolve_disposition(npc_id: str, player_id: str, npc: dict, *, queries=db_queries) -> str:
    disposition = await queries.get_npc_disposition(npc_id, player_id)
    if disposition is None:
        disposition = npc.get("default_disposition", "neutral")
    return disposition


@function_tool()
@db_tool
async def query_info(
    context: RunContext[SessionData],
    kind: Literal["location", "npc", "lore", "inventory", "settlement_population"],
    target_id: str | None = None,
) -> str:
    """Look up world info in one call. Set kind and (for most kinds) target_id:
    - kind="location", target_id=<location id>: scene details, atmosphere, exits.
    - kind="npc", target_id=<npc id>: personality, speech style, relationship-filtered knowledge.
    - kind="lore", target_id=<topic keyword>: history, gods, the Hollow, races, cultures.
    - kind="inventory": the current player's carried items (no target_id needed).
    - kind="settlement_population", target_id=<location id>: how many of each NPC role staff a
      settlement, scaled by its size (tier) and character (personality)."""
    return await _query_info_impl(context, kind, target_id)


async def _query_info_impl(
    context: RunContext[SessionData],
    kind: str,
    target_id: str | None = None,
) -> str:
    if kind == "inventory":
        return await _query_inventory_impl(context)
    if target_id is None:
        raise ToolError(f"query_info(kind={kind!r}) requires target_id.")
    if kind == "location":
        return await _query_location_impl(context, target_id)
    if kind == "npc":
        return await _query_npc_impl(context, target_id)
    if kind == "lore":
        return await _query_lore_impl(context, target_id)
    if kind == "settlement_population":
        return await _query_settlement_population_impl(context, target_id)
    raise ToolError(f"Unknown query_info kind: {kind!r}.")


async def _query_location_impl(
    context: RunContext[SessionData],
    location_id: str,
    *,
    content=db_content_queries,
) -> str:
    logger.info("query_info[location] called: location_id=%s", location_id)
    _validate_id(location_id, "location_id")
    location = await content.get_location(location_id)
    if location is None:
        raise ToolError(f"Location '{location_id}' not found.")

    session: SessionData = context.userdata
    location = apply_time_conditions(location, session.world_time)
    narration = _location_for_narration(location)
    return json.dumps(narration)


async def _query_settlement_population_impl(
    context: RunContext[SessionData],
    location_id: str,
    *,
    content=db_content_queries,
    rng=None,
) -> str:
    """Generate a settlement's NPC population (counts per role) from its tier + personality.

    Reads the location's settlement_tier/personality (story-001 fields) and delegates to the
    pure generate_settlement_npcs rules engine (story-003). Fail-loud (ADR 0002): an unknown
    or non-settlement location raises ToolError rather than returning an empty roster. `rng`
    is injectable for deterministic tests; production seeds it from location_id (concern
    b3c8b30eb849) so repeat queries of the same town return identical counts in- and
    cross-session, while distinct settlements still get distinct populations.
    """
    logger.info("query_info[settlement_population] called: location_id=%s", location_id)
    _validate_id(location_id, "location_id")
    location = await content.get_location(location_id)
    if location is None:
        raise ToolError(f"Location '{location_id}' not found.")
    tier = location.get("settlement_tier")
    personality = location.get("personality")
    if not tier or not personality:
        raise ToolError(f"Location '{location_id}' is not a settlement (no tier/personality).")
    seeded_rng = rng if rng is not None else random.Random(location_id)
    try:
        population = generate_settlement_npcs(tier, personality, rng=seeded_rng)
    except ValueError as e:
        raise ToolError(f"Cannot generate a settlement population for '{location_id}': {e}") from e
    return json.dumps(
        {
            "location_id": location_id,
            "settlement_tier": tier,
            "personality": personality,
            "population": population,
            "total": sum(population.values()),
        }
    )


async def _query_npc_impl(
    context: RunContext[SessionData],
    npc_id: str,
    *,
    queries=db_queries,
    content=db_content_queries,
) -> str:
    logger.info("query_info[npc] called: npc_id=%s", npc_id)
    _validate_id(npc_id, "npc_id")
    session: SessionData = context.userdata
    npc = await content.get_npc(npc_id)
    if npc is None:
        raise ToolError(f"NPC '{npc_id}' not found.")

    disposition = await _resolve_disposition(npc_id, session.player_id, npc, queries=queries)

    knowledge = filter_knowledge(npc.get("knowledge", {}), disposition)
    narration = _npc_for_narration(npc, disposition, knowledge)
    return json.dumps(narration)


async def _query_lore_impl(
    context: RunContext[SessionData],
    topic: str,
    *,
    content=db_content_queries,
) -> str:
    logger.info("query_info[lore] called: topic=%s", topic)
    entries = await content.search_lore(topic)
    if not entries:
        return json.dumps(
            {"note": f"No lore entries found for '{topic}'. Improvise from your general knowledge of Aethos."}
        )

    results = []
    for entry in entries:
        results.append(
            {
                "title": entry.get("title"),
                "category": entry.get("category"),
                "content": entry.get("content"),
                "tags": entry.get("tags", []),
            }
        )
    return json.dumps({"entries": results})


async def _query_inventory_impl(
    context: RunContext[SessionData],
    *,
    queries=db_queries,
) -> str:
    session: SessionData = context.userdata
    logger.info("query_info[inventory] called: player_id=%s", session.player_id)
    items = await queries.get_player_inventory(session.player_id)
    if not items:
        return json.dumps({"note": "This player's inventory is empty. They carry nothing of note."})

    results = []
    for item in items:
        results.append(
            {
                "name": item.get("name"),
                "type": item.get("type"),
                "description": item.get("description"),
                "rarity": item.get("rarity"),
                "effects": item.get("effects", []),
                "lore": item.get("lore"),
            }
        )
    return json.dumps({"items": results})
