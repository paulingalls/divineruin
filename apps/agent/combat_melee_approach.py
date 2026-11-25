"""One declaration shares its movement allowance across all melee strikes."""

import math
from typing import TYPE_CHECKING

from check_resolution_attack import _is_ranged
from combat_down import has_damage
from combat_movement_cost import crosses_low_ceiling, reachable_point
from combat_spatial import distance, number, position, require_spatial
from combat_spatial_declarations import apply_move, ineligible, resolve_traversal
from combat_structures import (
    THORNWALL,
    blocked_reason,
    blocking_wall,
    blocks_path,
    nearest_wall_point,
    stop_before_wall,
)
from condition_restrictions import effective_speed
from declarations import Declaration, DeclarationType
from encounter_actions import action_kind

if TYPE_CHECKING:
    from combat_fate_rolls import PacketRolls
    from combat_participant import CombatParticipant
    from combat_state import CombatState
    from session_data import SessionData


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


def melee_reach(action: dict) -> float:
    return number(action.get("reach", 10 if "reach" in action.get("properties", []) else 5), "reach", nonnegative=True)


def plan(state, actor, target, action, budget) -> tuple[dict, dict | None]:
    if not is_melee(action):
        return {}, None
    spatial = require_spatial(state)
    reach = melee_reach(action)
    origin, destination = position(spatial, actor.id), position(spatial, target.id)
    if target.is_structure and (segment := spatial.get("structures", {}).get(target.id)):
        destination = nearest_wall_point(origin, segment)
    separation = distance(origin, destination)
    ground_speed = effective_speed(spatial["speeds"][actor.id], actor.conditions)
    previous_allowance = budget.get("remaining")
    mode = "ground" if actor.fly_speed is None else "flying"
    speed = ground_speed if actor.fly_speed is None else effective_speed(actor.fly_speed, actor.conditions)
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
    if wall := blocking_wall(
        state, spatial, origin, destination, target_id=target.id, origin_id=actor.id, physical=True
    ):
        blocked = {**facts, "resolved": False, "attack_resolved": False, "reason": blocked_reason(wall)}
        if actor.is_ally or wall.structure_kind != THORNWALL or ineligible(actor) is not None:
            return blocked, None
        if separation <= reach:
            return {**blocked, "thornwall_id": wall.id}, None
        # The strike stays blocked however far the approach gets; contact needs the wall reached.
        facts.update(thornwall_blocked=wall.id, reason=blocked_reason(wall))
        # Shorten the route to the wall before any reach exits are computed from its endpoint.
        endpoint = reachable_point(
            spatial, actor.id, origin, destination, budget["remaining"], tidewalker=actor.tidewalker
        )
        segment = spatial["structures"][wall.id]
        if blocks_path(origin, endpoint, segment):
            endpoint = stop_before_wall(origin, endpoint, segment)
            facts["thornwall_id"] = wall.id
        if endpoint == origin:
            return finish(facts, destination, reach), None
        return facts, {"endpoint": endpoint, "mode": mode, "target": destination, "reach": reach}
    if separation <= reach:
        return facts, None
    reason = ineligible(actor)
    travel_needed = separation - reach
    if reason is None and budget["remaining"] > 0:
        desired = {
            axis: origin[axis] + (destination[axis] - origin[axis]) * travel_needed / separation for axis in origin
        }
        end = reachable_point(spatial, actor.id, origin, desired, budget["remaining"], tidewalker=actor.tidewalker)
        if mode == "flying" and crosses_low_ceiling(spatial, actor.id, origin, end):
            mode = "ground"
            budget["remaining"] = ground_speed if previous_allowance is None else previous_allowance
            end = reachable_point(spatial, actor.id, origin, desired, budget["remaining"], tidewalker=actor.tidewalker)
        if end != origin:
            return facts, {"endpoint": end, "mode": mode, "target": destination, "reach": reach}
    return finish(facts, destination, reach, reason), None


def leg_declaration(actor_id: str, endpoint: dict, mode: str) -> Declaration:
    return Declaration(DeclarationType.MANEUVER, "move", target_id=actor_id, destination=endpoint, movement_mode=mode)


def apply_leg(state, actor, facts: dict, endpoint: dict, mode: str, budget: dict) -> dict:
    moved = apply_move(
        state,
        actor,
        leg_declaration(actor.id, endpoint, mode),
        allowance=budget["remaining"],
    )
    return _record_leg(facts, moved, budget)


async def resolve_leg(
    session: "SessionData | None",
    state: "CombatState",
    actor: "CombatParticipant",
    facts: dict,
    endpoint: dict,
    mode: str,
    budget: dict,
    progress: "PacketRolls | None",
) -> dict | None:
    moved = await resolve_traversal(
        session,
        state,
        actor,
        leg_declaration(actor.id, endpoint, mode),
        allowance=budget["remaining"],
        progress=progress,
    )
    return None if moved is None else _record_leg(facts, moved, budget)


def _record_leg(facts: dict, moved: dict, budget: dict) -> dict:
    if "moved_ft" not in moved:
        return {**facts, **moved, "attack_resolved": False}
    travel = facts["moved_ft"] + moved["moved_ft"]
    spent = min(budget["remaining"], moved["movement_spent_ft"])
    budget["remaining"] -= spent
    result = {
        **facts,
        "moved_ft": travel,
        "movement_spent_ft": facts.get("movement_spent_ft", 0) + spent,
        "movement_mode": moved["movement_mode"],
        "destination": moved["destination"],
        "closed_distance": travel > 0,
        **({"left_pit": True} if moved.get("left_pit") else {}),
    }
    if "hearthfire_entries" in moved:
        result["hearthfire_entries"] = facts.get("hearthfire_entries", []) + moved["hearthfire_entries"]
    if not moved["resolved"]:
        result.update(resolved=False, attack_resolved=False, reason=moved["reason"])
    if moved.get("left_pit") or not moved["resolved"]:
        result.pop("thornwall_id", None)
    return result


def finish(facts: dict, target: dict, reach: float, reason: str | None = None) -> dict:
    if "thornwall_blocked" in facts:
        facts.update(resolved=False, attack_resolved=False)
        return facts
    remaining = distance(facts["destination"], target)
    facts["attack_resolved"] = reason is None and (remaining <= reach or math.isclose(remaining, reach, rel_tol=1e-12))
    if not facts["attack_resolved"]:
        facts["reason"] = (
            reason or f"Target remains {remaining:g} feet away, beyond reach {reach:g}; no movement speed remains"
        )
    return facts


async def prepare(
    session: "SessionData | None",
    state: "CombatState",
    actor: "CombatParticipant",
    target: "CombatParticipant",
    action: dict,
    budget: dict,
    *,
    progress: "PacketRolls | None" = None,
) -> dict | None:
    saved = progress.steps.pop("melee_plan", None) if progress is not None else None
    if saved is None:
        facts, route = plan(state, actor, target, action, budget)
    else:
        facts, route = saved["facts"], saved["route"]
        budget.update(saved["budget"])
    if route is None:
        return facts
    result = await resolve_leg(session, state, actor, facts, route["endpoint"], route["mode"], budget, progress)
    if result is None:
        assert progress is not None
        progress.steps["melee_plan"] = {"facts": facts, "route": route, "budget": budget}
        return None
    return finish(result, route["target"], route["reach"]) if result["resolved"] else result


async def prepare_packet(
    session: "SessionData",
    state: "CombatState",
    actor: "CombatParticipant",
    target: "CombatParticipant",
    action: dict,
    budget: dict,
    progress: "PacketRolls | None",
) -> dict | None:
    approach = progress.scope("melee_approach") if progress is not None else None
    if approach is not None and (settled := approach.steps.get("settled")) is not None:
        budget.update(settled["budget"])
        return settled["movement"]
    movement = await prepare(session, state, actor, target, action, budget, progress=approach)
    if approach is not None and movement is not None and "hearthfire_entries" in movement:
        approach.steps["settled"] = {"movement": movement, "budget": budget}
    return movement


def cache_held(state, head: dict, facts: dict, budget: dict) -> None:
    head.update(melee_approach=facts, movement_remaining=budget["remaining"])
    if "composite" in head:
        for sibling in state.held_actions:
            if sibling["actor_id"] == head["actor_id"] and sibling.get("composite") == head["composite"]:
                sibling["movement_remaining"] = budget["remaining"]
