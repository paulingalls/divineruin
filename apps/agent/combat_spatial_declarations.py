"""Movement uses one phase declaration and the actor's effective speed."""

from typing import TYPE_CHECKING

import aelora_hearthfire
from architect_encounter import is_owner
from combat_movement_cost import crosses_low_ceiling, movement_cost
from combat_spatial import distance, place, point, position, require_spatial
from combat_structures import THORNWALL, blocking_wall, stop_before_wall
from condition_restrictions import cannot_act, effective_speed, ignores_structures, speed_zero
from declarations import Declaration, DeclarationType, resolve_declaration

if TYPE_CHECKING:
    from combat_fate_rolls import PacketRolls
    from combat_participant import CombatParticipant
    from combat_state import CombatState
    from session_data import SessionData


class MovementRefused(ValueError):
    """A well-formed move whose route is unavailable on the current battlefield."""


class ThornwallMoveRefused(MovementRefused):
    """A Thornwall raised after declaration can stop a previously valid move."""


def is_move(declaration):
    return declaration.type is DeclarationType.MANEUVER and declaration.action == "move"


def movement_geometry(state, actor_id, declaration, *, allowance: float | None = None, hard_limit: bool = False):
    spatial = require_spatial(state)
    actor = state.get_participant(actor_id)
    if actor is None or declaration.target_id != actor_id:
        raise ValueError("move must target its own known actor")
    destination = point(declaration.destination)
    origin = position(spatial, actor_id)
    speed = effective_speed(spatial["speeds"][actor_id], actor.conditions) if allowance is None else allowance
    climbing = in_pit(state, actor_id)
    if climbing and not hard_limit:
        return origin, 0, speed, None
    spent = movement_cost(spatial, actor_id, origin, destination, tidewalker=actor.tidewalker)
    if declaration.movement_mode == "flying" and crosses_low_ceiling(spatial, actor_id, origin, destination):
        raise MovementRefused(f"{actor_id} cannot fly through a lowered ceiling")
    melody = actor.choir_movement_round == state.round_number or any(
        c["type"] == "charmed" and c.get("choir_melody") is True for c in actor.conditions
    )
    if spent > speed and (hard_limit or not melody):
        raise MovementRefused(f"{actor_id} move exceeds speed {speed:g} feet")
    if climbing:
        return origin, 0, speed, None
    wall = movement_blocker(state, spatial, actor, origin, destination)
    if wall is not None:
        reason = f"{actor_id} move is blocked by {wall.name} ({wall.id})"
        if wall.structure_kind != THORNWALL:
            raise MovementRefused(reason)
        if actor.is_ally:
            raise ThornwallMoveRefused(reason)
        destination = stop_before_wall(origin, destination, spatial["structures"][wall.id])
        spent = movement_cost(spatial, actor_id, origin, destination, tidewalker=actor.tidewalker)
    return destination, distance(origin, destination), spent, wall


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
    return blocking_wall(state, spatial, origin, destination, physical=True)


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
            try:
                validate_move(projection, actor_id, declaration, eligibility=False)
            except ThornwallMoveRefused:
                # A wall raised after declaration refuses the ally move at resolution, not the whole phase.
                continue


def apply_move(
    state: "CombatState", actor: "CombatParticipant", declaration: Declaration, *, allowance: float | None = None
) -> dict:
    if reason := ineligible(actor):
        return {"actor_id": actor.id, "resolved": False, "reason": reason}
    try:
        destination, travelled, spent, wall = movement_geometry(state, actor.id, declaration, allowance=allowance)
    except MovementRefused as error:
        return {"actor_id": actor.id, "resolved": False, "reason": str(error)}
    climbed = in_pit(state, actor.id)
    if climbed:
        assert state.architect_encounter is not None
        del state.architect_encounter["pits"][actor.id]
    facts = {
        "actor_id": actor.id,
        "resolved": True,
        "declaration_type": "maneuver",
        "moved_ft": travelled,
        "movement_spent_ft": spent,
        "movement_mode": declaration.movement_mode,
        **({"left_pit": True} if climbed else {}),
        **({"thornwall_id": wall.id, "reason": f"Stopped by {wall.name}"} if wall else {}),
        "destination": destination,
    }

    if climbed:
        return facts
    spatial = require_spatial(state)
    origin = position(spatial, actor.id)
    contacts = aelora_hearthfire.contacts(state, actor, origin, destination)
    if contacts:
        edge = contacts[0]["edge"]
        place(state, actor.id, edge)
        return {
            **_at_edge(spatial, actor, origin, edge, facts),
            "hearthfire_route": {"origin": origin, "contacts": contacts, "entries": [], "finish": facts},
        }
    place(state, actor.id, destination)
    return facts


def _at_edge(spatial: dict, actor: "CombatParticipant", origin: dict, edge: dict, finish: dict) -> dict:
    return {
        **{key: value for key, value in finish.items() if key not in ("thornwall_id", "reason")},
        "resolved": False,
        "reason": "Hearthfire stops movement",
        "destination": edge,
        "moved_ft": distance(origin, edge),
        "movement_spent_ft": movement_cost(spatial, actor.id, origin, edge, tidewalker=actor.tidewalker),
    }


async def resolve_traversal(
    session: "SessionData | None",
    state: "CombatState",
    actor: "CombatParticipant",
    declaration: Declaration,
    *,
    allowance: float | None = None,
    progress: "PacketRolls | None" = None,
) -> dict | None:
    pending = progress.steps.pop("hearthfire_move", None) if progress is not None else None
    if pending is None:
        facts = apply_move(state, actor, declaration, allowance=allowance)
        pending = facts.pop("hearthfire_route", None)
        if pending is None:
            return facts
    contacts, entries = pending["contacts"], pending["entries"]
    for index in range(len(entries), len(contacts)):
        contact = contacts[index]
        receipt = await aelora_hearthfire.settle_entry(session, state, actor, contact["zone_index"], progress)
        if receipt is None:
            assert progress is not None
            progress.steps["hearthfire_move"] = pending
            return None
        entries.append(receipt)
        if not receipt["success"]:
            facts = _at_edge(require_spatial(state), actor, pending["origin"], contact["edge"], pending["finish"])
            return {**facts, "reason": receipt["dm_cue"], "hearthfire_entries": entries}
        if index + 1 < len(contacts):
            place(state, actor.id, contacts[index + 1]["edge"])
    finish = pending["finish"]
    place(state, actor.id, finish["destination"])
    return {**finish, "hearthfire_entries": entries}


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
