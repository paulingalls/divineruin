"""One declaration shares its movement allowance across all melee strikes."""

import math

from check_resolution_attack import _is_ranged
from combat_down import has_damage
from combat_spatial import distance, number, position, require_spatial
from combat_spatial_declarations import apply_move, ineligible
from declarations import Declaration, DeclarationType
from encounter_actions import action_kind


def is_melee(action):
    return (
        action_kind(action) == "attack"
        and not action.get("auto_hit")
        and (
            action.get("type") == "melee"
            or (has_damage(action) and action.get("resolution") != "save" and action.get("half_on_success") is not True)
        )
        and not _is_ranged(action)
        and action.get("type") not in ("ranged", "area")
        and "aoe" not in action.get("properties", [])
    )


def prepare(state, actor, target, action, budget):
    if not is_melee(action):
        return {}
    spatial = require_spatial(state)
    reach = number(action.get("reach", 10 if "reach" in action.get("properties", []) else 5), "reach", nonnegative=True)
    origin, destination = position(spatial, actor.id), position(spatial, target.id)
    separation = distance(origin, destination)
    budget.setdefault("remaining", spatial["speeds"][actor.id])
    if actor.choir_movement_round == state.round_number:
        budget["remaining"] = 0
    facts = {
        "actor_id": actor.id,
        "resolved": True,
        "attack_resolved": True,
        "closed_distance": False,
        "moved_ft": 0,
        "destination": dict(origin),
    }
    if separation <= reach:
        return facts
    reason = ineligible(actor)
    travel = min(budget["remaining"], separation - reach) if reason is None else 0
    if travel > 0:
        end = {axis: origin[axis] + (destination[axis] - origin[axis]) * travel / separation for axis in origin}
        # A reconstructed diagonal can exceed speed by one ulp. Keep the internal move legal.
        while distance(origin, end) > travel:
            end = {axis: math.nextafter(end[axis], origin[axis]) for axis in end}
        moved = apply_move(
            state, actor, Declaration(type=DeclarationType.MANEUVER, action="move", target_id=actor.id, destination=end)
        )
        facts.update(moved_ft=moved["moved_ft"], destination=moved["destination"], closed_distance=True)
        budget["remaining"] = max(0, budget["remaining"] - travel)
    facts["attack_resolved"] = reason is None and separation - travel <= reach
    if not facts["attack_resolved"]:
        facts["reason"] = (
            reason
            or f"Target remains {separation - travel:g} feet away, beyond reach {reach:g}; no movement speed remains"
        )
    return facts


def prepare_held(state, head, action):
    actor = state.get_participant(head["actor_id"])
    target = state.get_participant(head["declaration"].get("target_id"))
    if action is None or target is None or not is_melee(action):
        return {}
    previous = head.get("melee_approach", {})
    if previous:
        return previous
    budget = {"remaining": head.get("movement_remaining", require_spatial(state)["speeds"][actor.id])}
    facts = prepare(state, actor, target, action, budget)
    head.update(melee_approach=facts, movement_remaining=budget["remaining"])
    if "composite" in head:
        for sibling in state.held_actions:
            if sibling["actor_id"] == actor.id and sibling.get("composite") == head["composite"]:
                sibling["movement_remaining"] = budget["remaining"]
    return facts
