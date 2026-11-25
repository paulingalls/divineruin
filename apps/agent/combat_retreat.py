"""Plan an ally's ground withdrawal and resolve it through combat movement."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import combat_cunning_action
import combat_spatial_declarations as moves
import thyra_thornwall
from combat_martial import standing_foe
from combat_melee_approach import leg_declaration
from combat_movement_cost import reachable_point
from combat_spatial import distance, position, require_spatial
from combat_structures import stop_before_wall
from condition_restrictions import effective_speed
from declarations import Declaration
from session_data import CombatParticipant, CombatState, SessionData

if TYPE_CHECKING:
    from asyncpg import Connection

    from combat_events import EventSink
    from combat_fate_rolls import PacketRolls
    from combat_player_movement import PlayerMovement


def _endpoint(state: CombatState, actor: CombatParticipant, spatial: dict, origin: dict) -> dict | None:
    foes = {foe.id: position(spatial, foe.id) for foe in state.participants if standing_foe(foe)}
    if not foes:
        return None

    dx = origin["x"] - math.fsum(point["x"] for point in foes.values()) / len(foes)
    dy = origin["y"] - math.fsum(point["y"] for point in foes.values()) / len(foes)
    if not (dx or dy):
        # A foe straight overhead gives no ground direction; the nearest foe that does decides.
        aside = {
            foe_id: point for foe_id, point in foes.items() if (point["x"], point["y"]) != (origin["x"], origin["y"])
        }
        if not aside:
            return None
        nearest = aside[min(aside, key=lambda foe_id: (distance(origin, aside[foe_id]), foe_id))]
        dx, dy = origin["x"] - nearest["x"], origin["y"] - nearest["y"]
    length = math.hypot(dx, dy)
    if not length:
        return None

    speed = effective_speed(spatial["speeds"][actor.id], actor.conditions)
    destination = {**origin, "x": origin["x"] + speed * dx / length, "y": origin["y"] + speed * dy / length}
    endpoint = reachable_point(spatial, actor.id, origin, destination, speed)
    wall = moves.movement_blocker(state, spatial, actor, origin, endpoint)
    if wall is not None:
        endpoint = stop_before_wall(origin, endpoint, spatial["structures"][wall.id])
    return endpoint


async def resolve(
    session: SessionData,
    state: CombatState,
    actor: CombatParticipant,
    declaration: Declaration,
    movement: PlayerMovement | None,
    *,
    conn: Connection | None,
    sink: EventSink | None,
    progress: PacketRolls | None,
    queries: Any,
) -> dict:
    spatial = require_spatial(state)
    origin = position(spatial, actor.id)
    route = movement.route if movement is not None else None
    endpoint = route["endpoint"] if route is not None else _endpoint(state, actor, spatial, origin)
    if endpoint is None:
        return {
            "actor_id": actor.id,
            "resolved": False,
            "declaration_type": "retreat",
            "reason": "no standing foe to retreat from",
            "destination": origin,
        }

    move = leg_declaration(actor.id, endpoint, "ground")
    flags = combat_cunning_action.movement_allowance(state, actor, declaration)
    disengage = flags.get("disengage", False)
    if movement is None:
        result = await thyra_thornwall.resolve_move(
            session, state, actor, move, conn=conn, sink=sink, progress=progress
        )
    else:
        result = await movement.move(actor, move, disengage=disengage)
    if result is None:
        return {}
    if disengage and result.get("movement_spent_ft", 0) > 0:
        await combat_cunning_action.pay(actor, queries=queries, conn=conn)
        result["cunning_action"] = {"rider": "disengage"}
    return {**result, "declaration_type": "retreat", "destination": position(spatial, actor.id)}
