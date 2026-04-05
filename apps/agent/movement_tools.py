"""Movement tools — player location changes and exit requirements."""

import json
import logging

from livekit.agents.llm import function_tool
from livekit.agents.voice import RunContext

import db
import db_content_queries
import db_mutations
import db_queries
import event_types as E
from db_errors import db_tool
from game_events import publish_game_event
from region_types import REGION_CITY
from session_data import SessionData
from tools import LOCATION_CORRUPTION, _resolve_ambient_sounds, _validate_id

logger = logging.getLogger("divineruin.tools")


async def _check_exit_requirement(requires: str, player_id: str) -> bool:
    """Evaluate an exit requirement string. Supports || (OR) branches.

    Patterns:
    - ``some_id.discovered`` -- checks player flag
    - ``skill_check:*`` -- always False (LLM should handle via tools first)
    """
    branches = [b.strip() for b in requires.split("||")]
    for branch in branches:
        if branch.startswith("skill_check:"):
            continue  # LLM must resolve via request_skill_check first
        if await db_queries.get_player_flag(player_id, branch):
            return True
    return False


@function_tool()
@db_tool
async def move_player(
    context: RunContext[SessionData],
    destination_id: str,
) -> str | tuple:
    """Move the player to a connected location. Provide the destination
    location ID from the current location's exits. Returns the full scene
    context for the new location."""
    logger.info("move_player called: destination_id=%s", destination_id)
    if err := _validate_id(destination_id, "destination_id"):
        return err
    session: SessionData = context.userdata

    current_location = await db_content_queries.get_location(session.location_id)
    if current_location is None:
        return json.dumps({"error": f"Current location '{session.location_id}' not found."})

    exits = current_location.get("exits", {})
    exit_entry = None
    for _direction, exit_data in exits.items():
        if isinstance(exit_data, dict) and exit_data.get("destination") == destination_id:
            exit_entry = exit_data
            break
        elif exit_data == destination_id:
            exit_entry = {"destination": destination_id}
            break

    if exit_entry is None:
        valid = [e.get("destination") if isinstance(e, dict) else e for e in exits.values()]
        return json.dumps(
            {
                "error": f"No exit to '{destination_id}' from current location.",
                "valid_destinations": valid,
            }
        )

    if isinstance(exit_entry, dict) and exit_entry.get("requires"):
        requirement = exit_entry["requires"]
        allowed = await _check_exit_requirement(requirement, session.player_id)
        if not allowed:
            # Return a narrative hint — do NOT expose raw flag names or DCs to the LLM
            hint = exit_entry.get(
                "blocked_hint",
                "Something prevents passage. The player needs to discover or overcome an obstacle first.",
            )
            return json.dumps(
                {
                    "blocked": True,
                    "destination": destination_id,
                    "message": hint,
                }
            )

    previous_location_id = session.location_id
    pending_events: list[tuple[str, dict]] = []

    destination_location = await db_content_queries.get_location(destination_id)

    # Detect region boundary crossing for handoff
    current_region = current_location.get("region_type", REGION_CITY)
    dest_region = destination_location.get("region_type", REGION_CITY) if destination_location else REGION_CITY
    region_change = current_region != dest_region

    destination_exits = destination_location.get("exits", {}) if destination_location else {}
    exit_connections = db.extract_exit_connections(destination_exits)

    async with db.transaction() as conn:
        await db_mutations.update_player_location(session.player_id, destination_id, conn=conn)
        await db_mutations.upsert_map_progress(session.player_id, destination_id, exit_connections, conn=conn)

        pending_events.append(
            (
                E.LOCATION_CHANGED,
                {
                    "previous_location": previous_location_id,
                    "new_location": destination_id,
                    "location_name": destination_location.get("name", destination_id)
                    if destination_location
                    else destination_id,
                    "atmosphere": destination_location.get("atmosphere", "") if destination_location else "",
                    "region": destination_location.get("region", "") if destination_location else "",
                    "connections": exit_connections,
                    "ambient_sounds": _resolve_ambient_sounds(destination_location, session.world_time),
                    "time_of_day": session.world_time,
                },
            )
        )

    # Session state updated ONLY after successful commit
    session.location_id = destination_id

    # Corruption tracking — location-based, resets on safe areas.
    # Updated after commit alongside location_id so both are consistent.
    new_corruption = LOCATION_CORRUPTION.get(destination_id, 0)
    previous_corruption = session.corruption_level
    session.corruption_level = new_corruption
    if new_corruption != previous_corruption:
        pending_events.append(
            (
                E.HOLLOW_CORRUPTION_CHANGED,
                {
                    "level": new_corruption,
                    "previous": previous_corruption,
                    "location_id": destination_id,
                },
            )
        )

    for event_type, payload in pending_events:
        await publish_game_event(session.room, event_type, payload, event_bus=session.event_bus)

    session.record_event(f"Moved to {destination_id}")
    loc_name = destination_location.get("name", destination_id) if destination_location else destination_id
    session.record_companion_memory(f"Traveled to {loc_name}")
    if destination_id not in session.session_locations_visited:
        session.session_locations_visited.append(destination_id)

    from scene_tools import _build_scene_context

    scene = await _build_scene_context(destination_id, session, location=destination_location)
    if "error" in scene:
        return json.dumps(scene)

    result = {"moved": True, "previous_location": previous_location_id, **scene}
    logger.info(
        "move_player result: %s → %s, %d NPCs, %d targets",
        previous_location_id,
        destination_id,
        len(result.get("npcs", [])),
        len(result.get("targets", [])),
    )
    json_str = json.dumps(result)

    if region_change:
        from livekit.agents.llm import ChatContext

        from gameplay_agent import create_gameplay_agent

        dest_name = destination_location.get("name", destination_id) if destination_location else destination_id
        atmosphere = destination_location.get("atmosphere", "") if destination_location else ""

        parts = [
            f"The player has arrived at {dest_name} ({dest_region} region).",
        ]
        if atmosphere:
            parts.append(f"The atmosphere is {atmosphere}.")
        if session.companion and session.companion.is_present:
            parts.append(f"{session.companion.name} is at the player's side.")
        parts.append(
            "Narrate the transition — describe what the player sees, hears, and feels "
            "as they enter this new area. Be vivid and sensory."
        )

        summary_ctx = ChatContext()
        summary_ctx.add_message(role="system", content=" ".join(parts))
        return create_gameplay_agent(
            dest_region, destination_id, companion=session.companion, chat_ctx=summary_ctx
        ), json_str

    return json_str
