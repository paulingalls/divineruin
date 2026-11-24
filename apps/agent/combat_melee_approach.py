"""One declaration shares its movement allowance across all melee strikes."""

import math

from check_resolution_attack import _is_ranged
from combat_down import has_damage
from combat_movement_cost import crosses_low_ceiling, reachable_point
from combat_spatial import distance, number, position, require_spatial
from combat_spatial_declarations import apply_move, ineligible
from combat_structures import blocked_reason, blocking_wall, nearest_wall_point
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
    if target.is_structure and (segment := spatial.get("structures", {}).get(target.id)):
        destination = nearest_wall_point(origin, segment)
    separation = distance(origin, destination)
    ground_speed = spatial["speeds"][actor.id]
    previous_allowance = budget.get("remaining")
    mode = "ground" if actor.fly_speed is None else "flying"
    speed = ground_speed if actor.fly_speed is None else actor.fly_speed
    budget.setdefault("remaining", speed)
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
    if wall := blocking_wall(state, spatial, origin, destination, target_id=target.id, origin_id=actor.id):
        return {**facts, "resolved": False, "attack_resolved": False, "reason": blocked_reason(wall)}
    if separation <= reach:
        return facts
    reason = ineligible(actor)
    travel = 0.0
    travel_needed = separation - reach
    if reason is None and budget["remaining"] > 0:
        desired = {
            axis: origin[axis] + (destination[axis] - origin[axis]) * travel_needed / separation for axis in origin
        }
        end = reachable_point(spatial, actor.id, origin, desired, budget["remaining"])
        if mode == "flying" and crosses_low_ceiling(spatial, actor.id, origin, end):
            mode = "ground"
            budget["remaining"] = ground_speed if previous_allowance is None else previous_allowance
            end = reachable_point(spatial, actor.id, origin, desired, budget["remaining"])
        if end != origin:
            moved = apply_move(
                state,
                actor,
                Declaration(
                    type=DeclarationType.MANEUVER,
                    action="move",
                    target_id=actor.id,
                    destination=end,
                    movement_mode=mode,
                ),
                allowance=budget["remaining"],
            )
            if not moved["resolved"]:
                return {**facts, **moved, "attack_resolved": False}
            travel = moved["moved_ft"]
            spent = min(budget["remaining"], moved["movement_spent_ft"])
            facts.update(
                moved_ft=travel,
                movement_spent_ft=spent,
                movement_mode=moved["movement_mode"],
                destination=moved["destination"],
                closed_distance=travel > 0,
            )
            if moved.get("left_pit"):
                facts["left_pit"] = True
            budget["remaining"] -= spent
    remaining = distance(facts["destination"], destination)
    facts["attack_resolved"] = reason is None and (remaining <= reach or math.isclose(remaining, reach, rel_tol=1e-12))
    if not facts["attack_resolved"]:
        facts["reason"] = (
            reason or f"Target remains {remaining:g} feet away, beyond reach {reach:g}; no movement speed remains"
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
    budget = {"remaining": head["movement_remaining"]} if "movement_remaining" in head else {}
    facts = prepare(state, actor, target, action, budget)
    head.update(melee_approach=facts, movement_remaining=budget["remaining"])
    if "composite" in head:
        for sibling in state.held_actions:
            if sibling["actor_id"] == actor.id and sibling.get("composite") == head["composite"]:
                sibling["movement_remaining"] = budget["remaining"]
    return facts
