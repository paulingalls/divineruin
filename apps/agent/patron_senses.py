"""Engine facts for Death's Awareness and Horizon Sense."""

from collections import deque

import db
import db_activity_queries
import db_content_queries
import db_queries
from patron_passives import warriors_endurance
from session_data import SessionData


async def deaths_awareness(session: SessionData, player: dict, *, queries=db_queries) -> dict:
    state = session.combat_state
    if state is not None:
        creatures = [
            {"id": participant.id, "name": participant.name}
            for participant in state.participants
            if not participant.is_dead and participant.hp_current * 4 <= participant.hp_max
        ]
    else:
        actor_id = session.acting_player_id
        creatures = []
        for member_id in session.party.member_ids:
            member = player if member_id == actor_id else await queries.get_player(member_id)
            if member is None:
                raise ValueError(f"Death's Awareness is missing party member {member_id!r}")
            if member.get("location_id") == session.location_id:
                hp = member["hp"]
                maximum = max(1, hp["max"] + member.get("maxhp_override", 0) + warriors_endurance(member))
                if hp["current"] * 4 <= maximum:
                    creatures.append({"id": member_id, "name": member["name"]})
    cue = (
        "Name the listed wounded creatures and party members without giving HP numbers."
        if creatures
        else "Say that you sense no badly wounded creatures within earshot."
    )
    return {"creatures": creatures, "narration_cue": cue}


def _nearest_unexplored(locations: dict[str, dict], start: str, visited: set[str]) -> dict | None:
    seen = {start}
    queue = deque([(start, 0)])
    while queue:
        location_id, legs = queue.popleft()
        if location_id not in locations:
            raise ValueError(f"Horizon Sense is missing location {location_id!r}")
        location = locations[location_id]
        if location_id not in visited:
            return {"name": location["name"], "legs": legs}
        for destination in sorted(db.extract_exit_connections(location.get("exits", {}))):
            if destination not in seen:
                seen.add(destination)
                queue.append((destination, legs + 1))
    return None


async def horizon_sense(
    session: SessionData, player: dict, *, content=db_content_queries, map_queries=db_activity_queries
) -> dict:
    hours = player.get("travel_hours_since_rest", 0)
    if type(hours) is not int or hours < 0:
        raise ValueError("Horizon Sense requires nonnegative integer travel hours")
    progress = await map_queries.get_player_map_progress(session.acting_player_id)
    visited = {session.location_id, *(entry["location_id"] for entry in progress)}
    nearest = _nearest_unexplored(await content.get_all_locations(), session.location_id, visited)
    cue = (
        "Give the recorded hours since the last long rest and the named unexplored location with its leg count."
        if nearest is not None
        else "Give the recorded hours since the last long rest and say there is nothing unexplored within reach."
    )
    return {"hours_traveled_since_long_rest": hours, "nearest_unexplored": nearest, "narration_cue": cue}
