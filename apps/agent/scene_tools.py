"""Scene resolution and context-building tools for the DM agent."""

import asyncio
import json
import logging

from livekit.agents.llm import function_tool
from livekit.agents.voice import RunContext

import db_queries
from db_errors import db_tool
from session_data import SessionData
from tools import (
    _location_for_narration,
    _npc_summary,
    _player_summary,
    _strip_hidden_dcs,
    _target_summary,
    _validate_id,
    apply_time_conditions,
)

logger = logging.getLogger("divineruin.tools")


def _resolve_scene_from_graph(scene_cache: dict[str, dict], quest: dict, current_stage: int) -> dict | None:
    """Look up scene from quest's scene_graph for the given stage."""
    for entry in quest.get("scene_graph", []):
        if current_stage in entry.get("stage_refs", []):
            return scene_cache.get(entry["scene_id"])
    return None


def get_active_scene_for_context(
    scene_cache: dict[str, dict],
    quest_cache: list[dict],
    location_data: dict | None,
) -> dict | None:
    """Resolve active scene: quest scene_graph first, then location default."""
    for quest in quest_cache:
        scene = _resolve_scene_from_graph(scene_cache, quest, quest.get("current_stage", 0))
        if scene:
            return scene
    if location_data:
        default_id = location_data.get("default_scene")
        if default_id:
            return scene_cache.get(default_id)
    return None


def detect_scene_transition(scene_cache: dict[str, dict], quest: dict, old_stage: int, new_stage: int) -> dict | None:
    """Detect scene transition using scene_graph + scene_cache."""
    if old_stage < 0:
        return None
    old_scene = _resolve_scene_from_graph(scene_cache, quest, old_stage)
    new_scene = _resolve_scene_from_graph(scene_cache, quest, new_stage)
    if old_scene is None or new_scene is None:
        return None
    if old_scene["id"] == new_scene["id"]:
        return None
    return {
        "old_scene": old_scene,
        "new_scene": new_scene,
        "region_changed": old_scene.get("region_type") != new_scene.get("region_type"),
    }


async def _build_scene_context(location_id: str, session: SessionData, location: dict | None = None) -> dict:
    if location is None:
        location = await db_queries.get_location(location_id)
    if location is None:
        return {"error": f"Location '{location_id}' not found."}

    location = apply_time_conditions(location, session.world_time)
    location = _strip_hidden_dcs(location)

    npcs_raw, targets_raw, player = await asyncio.gather(
        db_queries.get_npcs_at_location(location_id),
        db_queries.get_targets_at_location(location_id),
        db_queries.get_player(session.player_id),
    )

    npc_ids = [npc["id"] for npc in npcs_raw]
    dispositions = await db_queries.get_npc_dispositions(npc_ids, session.player_id) if npc_ids else {}
    npcs = []
    for npc in npcs_raw:
        disposition = dispositions.get(npc["id"], npc.get("default_disposition", "neutral"))
        npcs.append(_npc_summary(npc, disposition))

    targets = [_target_summary(t) for t in targets_raw]
    player_info = _player_summary(player) if player else None

    return {
        "location": _location_for_narration(location),
        "npcs": npcs,
        "targets": targets,
        "player": player_info,
    }


@function_tool()
@db_tool
async def enter_location(context: RunContext[SessionData], location_id: str) -> str:
    """Get everything about a location in one call: scene details, NPCs present,
    combat targets, and player status. Call this when entering a new area or
    starting a session. Use the returned IDs for follow-up tools like
    query_npc (for deeper NPC interaction) or request_attack (for combat)."""
    logger.info("enter_location called: location_id=%s", location_id)
    if err := _validate_id(location_id, "location_id"):
        return err
    session: SessionData = context.userdata

    result = await _build_scene_context(location_id, session)
    logger.info(
        "enter_location result: %d NPCs, %d targets at %s",
        len(result.get("npcs", [])),
        len(result.get("targets", [])),
        location_id,
    )
    return json.dumps(result)
