"""Movement uses one phase declaration and the actor's committed base speed."""

from combat_spatial import distance, point, position, require_spatial
from condition_restrictions import cannot_act, speed_zero
from declarations import DeclarationType


def is_move(declaration):
    return declaration.type is DeclarationType.MANEUVER and declaration.action == "move"


def movement_geometry(state, actor_id, declaration):
    spatial = require_spatial(state)
    if state.get_participant(actor_id) is None or declaration.target_id != actor_id:
        raise ValueError("move must target its own known actor")
    destination = point(declaration.destination)
    travelled = distance(position(spatial, actor_id), destination)
    if travelled > spatial["speeds"][actor_id]:
        raise ValueError(f"{actor_id} move exceeds speed {spatial['speeds'][actor_id]:g} feet")
    return destination, travelled


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
            validate_move(state, actor_id, declaration, eligibility=False)


def apply_move(state, actor, declaration):
    destination, travelled = validate_move(state, actor.id, declaration, eligibility=False)
    if reason := ineligible(actor):
        return {"actor_id": actor.id, "resolved": False, "reason": reason}
    state.spatial["positions"][actor.id] = destination
    return {
        "actor_id": actor.id,
        "resolved": True,
        "declaration_type": "maneuver",
        "moved_ft": travelled,
        "destination": destination,
    }


def preflight_state(state, origin_id):
    from declarations import resolve_declaration

    if state.spatial is not None:
        position(require_spatial(state), origin_id)
    pending = list(state.pending_declarations.items())
    held = [(head["actor_id"], head["declaration"]) for head in state.held_actions]
    for actor_id, raw in [*pending, *held]:
        if raw.get("action") == "move" or "destination" in raw:
            preflight(state, [(actor_id, resolve_declaration(raw))])
