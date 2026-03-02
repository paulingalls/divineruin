"""World query tools for the DM agent."""

import json

from livekit.agents.llm import function_tool
from livekit.agents.voice import RunContext

import db
from session_data import SessionData

DISPOSITION_TIERS = {
    "hostile": 0,
    "wary": 1,
    "neutral": 2,
    "cautious": 2,
    "friendly": 3,
    "trusted": 4,
}


def _disposition_rank(tier: str) -> int:
    return DISPOSITION_TIERS.get(tier.lower(), 2)


def filter_knowledge(knowledge: dict, disposition: str) -> list[str]:
    """Filter NPC knowledge by the player's disposition tier.

    Returns a flat list of knowledge strings the player is allowed to see.
    """
    rank = _disposition_rank(disposition)
    result: list[str] = []

    for gate, entries in knowledge.items():
        if gate == "free":
            if isinstance(entries, list):
                result.extend(entries)
        elif gate == "disposition >= friendly":
            if rank >= DISPOSITION_TIERS["friendly"] and isinstance(entries, list):
                result.extend(entries)
        elif gate == "disposition >= trusted":
            if rank >= DISPOSITION_TIERS["trusted"] and isinstance(entries, list):
                result.extend(entries)
        # quest_triggered and other gates: skip for 3.1

    return result


def apply_time_conditions(location: dict, time_of_day: str = "day") -> dict:
    """Apply time-of-day condition overrides to a location dict.

    Returns a new dict with overrides applied. Does not mutate the original.
    """
    conditions = location.get("conditions", {})
    time_condition = conditions.get("time_night") if time_of_day == "night" else None

    if time_condition is None:
        return location

    result = {**location}

    if "description_override" in time_condition:
        result["description"] = time_condition["description_override"]
    if "atmosphere" in time_condition:
        result["atmosphere"] = time_condition["atmosphere"]

    return result


def _strip_hidden_dcs(location: dict) -> dict:
    """Remove dc and discover_skill from hidden_elements so the LLM can't
    reveal them without a skill check."""
    hidden = location.get("hidden_elements")
    if not hidden:
        return location

    stripped = []
    for elem in hidden:
        stripped.append({
            "id": elem.get("id"),
            "description": elem.get("description"),
        })

    result = {**location, "hidden_elements": stripped}
    return result


def _location_for_narration(location: dict) -> dict:
    """Extract the fields the LLM needs for narrating a location."""
    return {
        "id": location.get("id"),
        "name": location.get("name"),
        "description": location.get("description"),
        "atmosphere": location.get("atmosphere"),
        "key_features": location.get("key_features", []),
        "hidden_elements": location.get("hidden_elements", []),
        "exits": location.get("exits", {}),
        "tags": location.get("tags", []),
    }


def _npc_for_narration(npc: dict, disposition: str, knowledge: list[str]) -> dict:
    """Extract the fields the LLM needs for roleplaying an NPC."""
    return {
        "name": npc.get("name"),
        "role": npc.get("role"),
        "personality": npc.get("personality"),
        "speech_style": npc.get("speech_style"),
        "mannerisms": npc.get("mannerisms"),
        "appearance": npc.get("appearance"),
        "disposition": disposition,
        "knowledge": knowledge,
        "voice_notes": npc.get("voice_notes"),
    }


@function_tool()
async def query_location(context: RunContext[SessionData], location_id: str) -> str:
    """Get location details by ID: description, atmosphere, features, exits.
    Use for scene descriptions and navigation."""
    location = await db.get_location(location_id)
    if location is None:
        return json.dumps({"error": f"Location '{location_id}' not found."})

    location = apply_time_conditions(location)
    location = _strip_hidden_dcs(location)
    narration = _location_for_narration(location)
    return json.dumps(narration)


@function_tool()
async def query_npc(context: RunContext[SessionData], npc_id: str) -> str:
    """Get NPC details by ID: personality, speech style, knowledge filtered by
    the player's relationship. Use to roleplay NPCs accurately."""
    session: SessionData = context.userdata
    npc = await db.get_npc(npc_id)
    if npc is None:
        return json.dumps({"error": f"NPC '{npc_id}' not found."})

    disposition = await db.get_npc_disposition(npc_id, session.player_id)
    if disposition is None:
        disposition = npc.get("default_disposition", "neutral")

    knowledge = filter_knowledge(npc.get("knowledge", {}), disposition)
    narration = _npc_for_narration(npc, disposition, knowledge)
    return json.dumps(narration)


@function_tool()
async def query_lore(context: RunContext[SessionData], topic: str) -> str:
    """Search world lore by topic keyword. Use for history, gods, the Hollow,
    races, cultures, and world events."""
    entries = await db.search_lore(topic)
    if not entries:
        return json.dumps({
            "note": f"No lore entries found for '{topic}'. "
            "Improvise from your general knowledge of Aethos."
        })

    results = []
    for entry in entries:
        results.append({
            "title": entry.get("title"),
            "category": entry.get("category"),
            "content": entry.get("content"),
            "tags": entry.get("tags", []),
        })
    return json.dumps({"entries": results})


@function_tool()
async def query_inventory(context: RunContext[SessionData], player_id: str) -> str:
    """Get a player's inventory items. Use when they ask what they are carrying."""
    items = await db.get_player_inventory(player_id)
    if not items:
        return json.dumps({
            "note": "This player's inventory is empty. "
            "They carry nothing of note."
        })

    results = []
    for item in items:
        results.append({
            "name": item.get("name"),
            "type": item.get("type"),
            "description": item.get("description"),
            "rarity": item.get("rarity"),
            "effects": item.get("effects", []),
            "lore": item.get("lore"),
        })
    return json.dumps({"items": results})
