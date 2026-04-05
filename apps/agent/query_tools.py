"""World query tools for the DM agent."""

import json
import logging

from livekit.agents.llm import function_tool
from livekit.agents.voice import RunContext

import db_content_queries
import db_queries
from db_errors import db_tool
from session_data import SessionData
from tools import (
    _location_for_narration,
    _npc_for_narration,
    _strip_hidden_dcs,
    _validate_id,
    apply_time_conditions,
    filter_knowledge,
)

logger = logging.getLogger("divineruin.tools")


async def _resolve_disposition(npc_id: str, player_id: str, npc: dict) -> str:
    disposition = await db_queries.get_npc_disposition(npc_id, player_id)
    if disposition is None:
        disposition = npc.get("default_disposition", "neutral")
    return disposition


@function_tool()
@db_tool
async def query_location(context: RunContext[SessionData], location_id: str) -> str:
    """Get location details by ID: description, atmosphere, features, exits.
    Use for scene descriptions and navigation."""
    logger.info("query_location called: location_id=%s", location_id)
    if err := _validate_id(location_id, "location_id"):
        return err
    location = await db_content_queries.get_location(location_id)
    if location is None:
        return json.dumps({"error": f"Location '{location_id}' not found."})

    session: SessionData = context.userdata
    location = apply_time_conditions(location, session.world_time)
    location = _strip_hidden_dcs(location)
    narration = _location_for_narration(location)
    return json.dumps(narration)


@function_tool()
@db_tool
async def query_npc(context: RunContext[SessionData], npc_id: str) -> str:
    """Get NPC details by ID: personality, speech style, knowledge filtered by
    the player's relationship. Use to roleplay NPCs accurately."""
    logger.info("query_npc called: npc_id=%s", npc_id)
    if err := _validate_id(npc_id, "npc_id"):
        return err
    session: SessionData = context.userdata
    npc = await db_content_queries.get_npc(npc_id)
    if npc is None:
        return json.dumps({"error": f"NPC '{npc_id}' not found."})

    disposition = await _resolve_disposition(npc_id, session.player_id, npc)

    knowledge = filter_knowledge(npc.get("knowledge", {}), disposition)
    narration = _npc_for_narration(npc, disposition, knowledge)
    return json.dumps(narration)


@function_tool()
@db_tool
async def query_lore(context: RunContext[SessionData], topic: str) -> str:
    """Search world lore by topic keyword. Use for history, gods, the Hollow,
    races, cultures, and world events."""
    logger.info("query_lore called: topic=%s", topic)
    entries = await db_content_queries.search_lore(topic)
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


@function_tool()
@db_tool
async def query_inventory(context: RunContext[SessionData]) -> str:
    """Get the current player's inventory items. Use when they ask what they are carrying."""
    session: SessionData = context.userdata
    logger.info("query_inventory called: player_id=%s", session.player_id)
    items = await db_queries.get_player_inventory(session.player_id)
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
