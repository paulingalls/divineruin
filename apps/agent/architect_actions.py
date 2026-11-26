"""Resolve the Architect's structure-dependent attacks."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import architect_encounter
import combat_spatial
import combat_structures
import combat_wrongdoing
import dice
from architect_encounter import CATHEDRAL, CATHEDRAL_RADIUS_FT, CONSTRUCT_SLAM, cathedral_ids
from combat_damage import apply_attack_result
from combat_damage_results import AutomaticDamageResult
from combat_down import damage_target_unavailable

if TYPE_CHECKING:
    from combat_participant import CombatParticipant
    from combat_state import CombatState


GEOMETRY = "Geometry Strike"


def is_cathedral(state: CombatState, actor_id: str, action: dict) -> bool:
    return action["name"].casefold() == CATHEDRAL.casefold() and architect_encounter.is_owner(state, actor_id)


def raise_cathedral(state: CombatState, owner_id: str) -> list[str]:
    spatial = combat_spatial.require_spatial(state)
    zone_id, center_id = cathedral_ids(owner_id)
    occupied_ids = spatial["positions"].keys() | spatial["locations"].keys() | spatial["zones"].keys()
    if occupied_ids & {zone_id, center_id}:
        raise ValueError("Cathedral spatial IDs are already in use")
    center = combat_spatial.position(spatial, owner_id)
    spatial["locations"][center_id] = center
    spatial["zones"][zone_id] = {"kind": "cathedral", "center_id": center_id, "radius_ft": CATHEDRAL_RADIUS_FT}
    return [
        target.id
        for target in state.participants
        if target.id != owner_id
        and not target.is_structure
        and not damage_target_unavailable(target)
        and combat_spatial.inside(center, combat_spatial.position(spatial, target.id), CATHEDRAL_RADIUS_FT)
    ]


def geometry_auto_hit(
    state: CombatState, actor_id: str, action: dict, target_id: str | None, head: dict | None
) -> bool:
    if action["name"] != GEOMETRY or not architect_encounter.is_owner(state, actor_id):
        return False
    if head is not None:
        if "architect_attack" in head:
            return True
        if head.get("roll") is not None or head.get("fate_attack") is not None:
            return False
    if target_id is None or state.get_participant(target_id) is None:
        return False
    spatial = combat_spatial.require_spatial(state)
    record = state.architect_encounter
    assert record is not None
    origin = combat_spatial.position(spatial, target_id)
    walls = spatial.get("structures", {})
    return any(
        combat_spatial.distance(origin, combat_structures.nearest_wall_point(origin, walls[wall_id])) <= 5
        for wall_id in record["structure_ids"]
        if wall_id in walls
    )


def slam_refusal(state: CombatState, actor_id: str, action: dict, target_id: str) -> str | None:
    if action["name"] != CONSTRUCT_SLAM or not architect_encounter.is_owner(state, actor_id):
        return None
    target = state.get_participant(target_id)
    if target is None or target.is_structure:
        return None
    spatial = combat_spatial.require_spatial(state)
    actor, origin = (combat_spatial.position(spatial, id_) for id_ in (actor_id, target_id))
    if (actor["x"], actor["y"]) == (origin["x"], origin["y"]):
        return "Construct Slam requires horizontal separation to push away from the Architect."
    return None


def _push(state: CombatState, actor_id: str, target_id: str) -> dict:
    spatial = combat_spatial.require_spatial(state)
    actor, origin = (combat_spatial.position(spatial, id_) for id_ in (actor_id, target_id))
    dx, dy = (origin[axis] - actor[axis] for axis in ("x", "y"))
    length = math.hypot(dx, dy)
    if length == 0:
        raise ValueError("Construct Slam requires horizontal separation")
    destination = {**origin, "x": origin["x"] + 15 * (dx / length), "y": origin["y"] + 15 * (dy / length)}
    wall_id = None
    if hit := combat_structures.first_wall_contact(spatial, origin, destination):
        wall_id, destination, fraction = hit
        if fraction:
            wall = spatial["structures"][wall_id]
            # Point contact blocks subsequent voluntary movement and targeting.
            while combat_structures.blocks_path(origin, destination, wall):
                destination = {axis: math.nextafter(value, origin[axis]) for axis, value in destination.items()}
    movement = combat_spatial.force_place(state, target_id, destination)
    return {**movement, "wall_id": None if "movement_blocked" in movement else wall_id}


async def _automatic_damage(
    session,
    state: CombatState,
    actor: CombatParticipant,
    target: CombatParticipant,
    action: dict,
    amount: int,
    damage_type: str,
    context: str,
    deps: dict,
) -> dict:
    keys = ("mutations", "queries", "concentration_break_mod", "conn", "sink")
    return await apply_attack_result(
        session,
        actor,
        {"name": action["name"]},
        target,
        AutomaticDamageResult(amount, damage_type, context=context),
        target.ac,
        combat_state=state,
        publish_roll=False,
        progress=_scope(deps.get("progress"), context),
        **{key: deps[key] for key in keys},
    )


def _scope(progress, name: str):
    return progress.scope(name) if progress is not None else None


async def resolve(
    session,
    state: CombatState,
    packet,
    actor: CombatParticipant,
    target: CombatParticipant,
    action: dict,
    head: dict | None,
    deps: dict,
) -> dict:
    from combat_fate import attack_sequence

    if not architect_encounter.is_owner(state, actor.id):
        return await attack_sequence(session, state, packet, actor, target, action, **deps)

    progress = deps.get("progress")
    steps = head if head is not None else {}
    if geometry_auto_hit(state, actor.id, action, target.id, head):
        if "architect_attack" not in steps:
            combat_wrongdoing.record_attack(state, actor, target)
            steps["architect_attack"] = {"damage": dice.roll(action["damage"]).total}
        result = await _automatic_damage(
            session,
            state,
            actor,
            target,
            action,
            steps["architect_attack"]["damage"],
            action["damage_type"],
            "geometry_strike",
            deps,
        )
        if progress is not None and progress.paused:
            return {}
        state.first_attack_resolved = True
        return {**result, "actor_id": actor.id, "resolved": True, "hit": True, "automatic_hit": True}

    if action["name"] != CONSTRUCT_SLAM:
        return await attack_sequence(session, state, packet, actor, target, action, **deps)
    if "architect_attack" not in steps:
        if reason := slam_refusal(state, actor.id, action, target.id):
            return {"actor_id": actor.id, "resolved": False, "reason": reason}
        base = await attack_sequence(
            session, state, packet, actor, target, action, **{**deps, "progress": _scope(progress, "slam_base")}
        )
        if progress is not None and progress.paused:
            return {}
        if not base.get("hit") or target.is_structure:
            return base
        push = _push(state, actor.id, target.id)
        if push["wall_id"] is None:
            return {**base, "push": push}
        steps["architect_attack"] = {"base": base, "push": push, "damage": dice.roll("2d6").total}
    receipt = steps["architect_attack"]
    collision = await _automatic_damage(
        session,
        state,
        actor,
        target,
        action,
        receipt["damage"],
        "bludgeoning",
        "slam_collision",
        deps,
    )
    if progress is not None and progress.paused:
        return {}
    base = receipt["base"]
    if "damage_target_id" not in base:
        base = {
            **base,
            "target_hp_status": collision["target_hp_status"],
            "target_fallen": collision["target_fallen"],
            "concentration_broken": collision["concentration_broken"] or base["concentration_broken"],
        }
    return {**base, "push": receipt["push"], "collision": collision}


def validate_continuations(state: CombatState) -> None:
    scopes = {"geometry_strike", "slam_collision"}
    for head in state.held_actions:
        if "architect_attack" not in head and not (scopes & head.get("roll_steps", {}).keys()):
            continue
        _validate_continuation(state, head)


def _validate_continuation(state: CombatState, head: dict) -> None:
    from combat_action_availability import replay_valid
    from declarations import resolve_declaration

    invalid = "Invalid Architect attack continuation"
    actor = state.get_participant(head["actor_id"])
    if actor is None or not architect_encounter.is_owner(state, actor.id):
        raise ValueError(invalid)
    declaration = resolve_declaration(head["declaration"])
    action = next((a for a in actor.action_pool if a["name"] == declaration.action), None)
    if action is None or not replay_valid(state, head, actor, action, declaration):
        raise ValueError(invalid)
    if declaration.target_id is None or state.get_participant(declaration.target_id) is None:
        raise ValueError(invalid)
    receipt = head.get("architect_attack")
    if not isinstance(receipt, dict) or type(receipt.get("damage")) is not int or receipt["damage"] < 0:
        raise ValueError(invalid)
    if action["name"] == GEOMETRY:
        if set(receipt) != {"damage"} or head.get("roll") is not None or head.get("fate_attack") is not None:
            raise ValueError(invalid)
        return
    if action["name"] != CONSTRUCT_SLAM or set(receipt) != {"base", "push", "damage"} or head.get("roll") is None:
        raise ValueError(invalid)
    base, push = receipt["base"], receipt["push"]
    if not isinstance(base, dict) or base.get("hit") is not True or not isinstance(push, dict):
        raise ValueError(invalid)
    if set(push) != {"distance_ft", "destination", "wall_id"}:
        raise ValueError(invalid)
    wall = state.get_participant(push["wall_id"])
    if wall is None or not wall.is_structure:
        raise ValueError(invalid)
    combat_spatial.point(push["destination"])
    distance = push["distance_ft"]
    if type(distance) not in (int, float) or not 0 <= distance <= 15.000001:
        raise ValueError(invalid)
