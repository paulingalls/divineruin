"""Movement uses one phase declaration and the actor's committed base speed."""

from architect_encounter import is_owner
from combat_movement_cost import crosses_low_ceiling, movement_cost
from combat_spatial import distance, place, point, position, require_spatial
from combat_structures import blocking_wall
from condition_restrictions import cannot_act, ignores_structures, speed_zero
from declarations import DeclarationType, resolve_declaration


class MovementRefused(ValueError):
    """A well-formed move whose route is unavailable on the current battlefield."""


def is_move(declaration):
    return declaration.type is DeclarationType.MANEUVER and declaration.action == "move"


def movement_geometry(state, actor_id, declaration, *, allowance=None):
    spatial = require_spatial(state)
    actor = state.get_participant(actor_id)
    if actor is None or declaration.target_id != actor_id:
        raise ValueError("move must target its own known actor")
    destination = point(declaration.destination)
    origin = position(spatial, actor_id)
    speed = spatial["speeds"][actor_id] if allowance is None else allowance
    if in_pit(state, actor_id):
        return origin, 0, speed
    travelled = distance(origin, destination)
    spent = movement_cost(spatial, actor_id, origin, destination)
    if declaration.movement_mode == "flying" and crosses_low_ceiling(spatial, actor_id, origin, destination):
        raise MovementRefused(f"{actor_id} cannot fly through a lowered ceiling")
    melody = actor.choir_movement_round == state.round_number or any(
        c["type"] == "charmed" and c.get("choir_melody") is True for c in actor.conditions
    )
    if spent > speed and not melody:
        raise MovementRefused(f"{actor_id} move exceeds speed {speed:g} feet")
    if wall := movement_blocker(state, spatial, actor, origin, destination):
        raise MovementRefused(f"{actor_id} move is blocked by {wall.name} ({wall.id})")
    return destination, travelled, spent


def in_pit(state, actor_id):
    return state.architect_encounter is not None and actor_id in state.architect_encounter["pits"]


def movement_blocker(state, spatial, actor, origin, destination):
    if ignores_structures(actor.conditions):
        return None
    if is_owner(state, actor.id):
        owned = state.architect_encounter["structure_ids"]
        spatial = {
            **spatial,
            "structures": {key: value for key, value in spatial.get("structures", {}).items() if key not in owned},
        }
    return blocking_wall(state, spatial, origin, destination)


def ineligible(actor):
    if actor.is_fallen:
        return "actor unavailable"
    if blocked := cannot_act(actor.conditions) or speed_zero(actor.conditions):
        return f"{actor.id} is {blocked[0]} and cannot move"
    return None


def validate_move(state, actor_id, declaration, *, eligibility=True):
    geometry = movement_geometry(state, actor_id, declaration)
    actor = state.get_participant(actor_id)
    if eligibility and (reason := ineligible(actor)):
        raise ValueError(reason)
    return geometry


def preflight(state, declarations):
    for actor_id, declaration in declarations:
        if is_move(declaration):
            if declaration.reshape:
                from architect_reshape import proposed_state

                projection = proposed_state(state, actor_id, declaration.reshape)
            else:
                projection = state
            validate_move(projection, actor_id, declaration, eligibility=False)


def apply_move(state, actor, declaration, *, allowance=None):
    if reason := ineligible(actor):
        return {"actor_id": actor.id, "resolved": False, "reason": reason}
    try:
        destination, travelled, spent = movement_geometry(state, actor.id, declaration, allowance=allowance)
    except MovementRefused as error:
        return {"actor_id": actor.id, "resolved": False, "reason": str(error)}
    climbed = in_pit(state, actor.id)
    if climbed:
        del state.architect_encounter["pits"][actor.id]
    else:
        place(state, actor.id, destination)
    return {
        "actor_id": actor.id,
        "resolved": True,
        "declaration_type": "maneuver",
        "moved_ft": travelled,
        "movement_spent_ft": spent,
        **({"left_pit": True} if climbed else {}),
        "destination": destination,
    }


def preflight_state(state):
    """Check persisted moves before a transaction. Reshape can change a held route before its turn."""
    if state.spatial is not None:
        require_spatial(state)
    for head in state.held_actions:
        raw = head["declaration"]
        if raw.get("action") == "move" or "destination" in raw:
            declaration = resolve_declaration(raw)
            if not is_move(declaration) or declaration.target_id != head["actor_id"]:
                raise ValueError("held move must target its own actor")
            if state.architect_encounter is None:
                preflight(state, [(head["actor_id"], declaration)])
