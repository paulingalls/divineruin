"""Replace a turned creature's ordinary action with movement away from the caster."""

import math
from typing import TYPE_CHECKING

import combat_spatial_declarations as moves
import thyra_thornwall
from combat_melee_approach import leg_declaration
from combat_movement_cost import reachable_point
from combat_spatial import position, require_spatial
from combat_structures import THORNWALL, stop_before_wall
from condition_restrictions import effective_speed

if TYPE_CHECKING:
    from asyncpg import Connection

    from combat_events import EventSink
    from combat_fate_rolls import PacketRolls
    from session_data import CombatParticipant, CombatState, SessionData


def flight_condition(actor: "CombatParticipant") -> dict | None:
    return next((c for c in actor.conditions if c["type"] == "frightened" and "turn_undead" in c), None)


def is_flight_turn(actor: "CombatParticipant", head: dict) -> bool:
    return not (head.get("opportunity_attack") or "legendary_kind" in head) and flight_condition(actor) is not None


def _route(state: "CombatState", actor: "CombatParticipant", source_id: str) -> dict:
    if state.get_participant(source_id) is None:
        raise ValueError(f"Missing Turn Undead/Hollow caster {source_id}")
    spatial = require_spatial(state)
    origin, source = position(spatial, actor.id), position(spatial, source_id)
    dx, dy = origin["x"] - source["x"], origin["y"] - source["y"]
    if dx == dy == 0:
        dx = 1
    length = math.hypot(dx, dy)
    speed = effective_speed(spatial["speeds"][actor.id], actor.conditions)
    destination = {**origin, "x": origin["x"] + speed * dx / length, "y": origin["y"] + speed * dy / length}
    endpoint = reachable_point(spatial, actor.id, origin, destination, speed, tidewalker=actor.tidewalker)
    wall = moves.movement_blocker(state, spatial, actor, origin, endpoint)
    # Thornwall's own movement path stops the creature and resolves contact.
    if wall is not None and wall.structure_kind != THORNWALL:
        endpoint = stop_before_wall(origin, endpoint, spatial["structures"][wall.id])
    return {"origin": origin, "endpoint": endpoint, "blocked_by": wall.name if wall else None}


async def flee(
    session: "SessionData",
    state: "CombatState",
    actor: "CombatParticipant",
    *,
    conn: "Connection | None",
    sink: "EventSink | None",
    progress: "PacketRolls | None",
) -> dict:
    condition = flight_condition(actor)
    assert condition is not None
    metadata = condition["turn_undead"]
    source_id = condition["source"]
    if metadata.get("fled_round") == state.round_number:
        return {"actor_id": actor.id, "resolved": False, "reason": "Already used this turn to flee."}
    steps = progress.steps if progress is not None else {}
    route = steps.get("route")
    if route is None:
        steps["route"] = route = _route(state, actor, source_id)
    movement = await thyra_thornwall.resolve_move(
        session,
        state,
        actor,
        leg_declaration(actor.id, route["endpoint"], "ground"),
        conn=conn,
        sink=sink,
        progress=progress,
    )
    if progress is not None and progress.paused:
        return {}
    metadata["fled_round"] = state.round_number
    fled = movement.get("moved_ft", 0) > 0
    reason = movement.get("reason")
    if reason is None:
        if fled and route["blocked_by"]:
            reason = f"Fled from the caster until stopped by {route['blocked_by']}."
        elif fled:
            reason = "Fled from the caster."
        elif route["blocked_by"]:
            reason = f"Tried to flee but was blocked by {route['blocked_by']}."
        elif movement.get("left_pit"):
            reason = "Climbed out of the pit while fleeing."
        else:
            reason = "Tried to flee but had no movement available."
    return {**movement, "source_id": source_id, "origin": route["origin"], "fled": fled, "reason": reason}
