"""Resolve Architect terrain operations before the packet's ordinary action."""

from __future__ import annotations

from copy import deepcopy
from functools import partial
from math import isclose
from typing import TYPE_CHECKING

import architect_encounter
import check_resolution_save
import combat_spatial
import combat_structures
import dice
from combat_condition_landing import _land_condition_on_one
from combat_damage import apply_attack_result
from combat_damage_results import AutomaticDamageResult
from combat_fate_rolls import PacketRolls, packet_save
from combat_movement_cost import rectangle
from condition_restrictions import cannot_act

if TYPE_CHECKING:
    from combat_participant import CombatParticipant
    from combat_state import CombatState
    from session_data import SessionData

MAX_SECTION_FT = 20
MAX_RANGE_FT = 120


def remaining(state: CombatState, owner: CombatParticipant) -> int:
    record = state.architect_encounter
    assert record is not None
    used = record["reshape_count"] if record["reshape_round"] == state.round_number else 0
    capacity = 2 if owner.hp_current * 2 < owner.hp_max else 1
    return max(0, capacity - used)


def proposed_state(state: CombatState, actor_id: str, operations: list[dict]) -> CombatState:
    actor = state.get_participant(actor_id)
    if not architect_encounter.is_owner(state, actor_id):
        raise ValueError("Only the Architect can Reshape")
    if actor is None or actor.is_fallen or actor.is_dead or actor.hp_current <= 0 or cannot_act(actor.conditions):
        raise ValueError("The Architect is unavailable to Reshape")
    available = remaining(state, actor)
    if len(operations) > available:
        raise ValueError(f"Reshape budget exceeded: {available} use(s) remain this round")
    proposal = deepcopy(state)
    for op in operations:
        place_section(proposal, actor_id, op)
    return proposal


def _range(origin: dict, *points: dict) -> None:
    if any(combat_spatial.distance(origin, point) > MAX_RANGE_FT for point in points):
        raise ValueError("Reshape section exceeds the 120-foot range")


def _wall(state: CombatState, spatial: dict, origin: dict, operation: dict) -> CombatParticipant:
    record = state.architect_encounter
    assert record is not None
    wall_id = operation["wall_id"]
    if wall_id not in record["structure_ids"] or wall_id not in spatial["structures"]:
        raise ValueError("Reshape requires a live wall owned by the Architect")
    wall = state.get_participant(wall_id)
    assert wall is not None
    _range(origin, *spatial["structures"][wall_id].values())
    return wall


def place_section(state: CombatState, actor_id: str, operation: dict, *, shift_wall: bool = False) -> dict:
    """Apply one checked section. Floor victims resolve separately and can pause."""
    spatial = combat_spatial.require_spatial(state)
    record = state.architect_encounter
    assert record is not None
    origin = combat_spatial.position(spatial, actor_id)
    kind = operation["kind"]
    if shift_wall:
        return _shift_wall(state, operation)
    if kind == "destroy_wall":
        wall = _wall(state, spatial, origin, operation)
        combat_structures.collapse_wall(state, wall)
        return {"kind": kind, "section_id": wall.id}
    if kind in ("create_wall", "move_wall"):
        start, end = operation["start"], operation["end"]
        _range(origin, start, end)
        if combat_spatial.distance(start, end) > MAX_SECTION_FT:
            raise ValueError("Reshape wall exceeds the 20-foot section limit")
        if kind == "move_wall":
            wall_id = _wall(state, spatial, origin, operation).id
            combat_structures.move_wall(state, wall_id, start, end)
        else:
            wall_id = f"{actor_id}_reshape_wall_{len(record['structure_ids'])}"
            combat_structures.add_wall(state, wall_id, "Architect's wall", start, end)
            record["structure_ids"].append(wall_id)
        return {"kind": kind, "section_id": wall_id}

    low, high = rectangle(operation["min"], operation["max"])
    if any(high[axis] - low[axis] > MAX_SECTION_FT for axis in ("x", "y")):
        raise ValueError("Reshape rectangle exceeds the 20-foot section limit")
    _range(origin, low, high, {**low, "x": high["x"]}, {**low, "y": high["y"]})
    if kind == "lower_ceiling":
        areas = spatial["movement_areas"]
        section_id = f"{actor_id}_ceiling_{len(areas)}"
        areas[section_id] = {
            "kind": "low_ceiling",
            "excluded_actor_ids": [],
            "shape": "rectangle",
            "min": low,
            "max": high,
        }
        return {"kind": kind, "section_id": section_id}
    if kind != "open_floor":
        raise ValueError(f"Unknown Reshape operation {kind!r}")
    floors = record["floors"]
    section_id = f"{actor_id}_floor_{len(floors)}"
    floors[section_id] = {"min": low, "max": high}
    targets = []
    for target in state.participants:
        pos = combat_spatial.position(spatial, target.id)
        if (
            not target.is_structure
            and not target.is_dead
            and pos["z"] == low["z"]
            and all(low[axis] <= pos[axis] <= high[axis] for axis in ("x", "y"))
        ):
            targets.append(target.id)
    return {"kind": kind, "section_id": section_id, "targets": targets, "results": []}


def _shift_wall(state: CombatState, operation: dict) -> dict:
    spatial = combat_spatial.require_spatial(state)
    record = state.architect_encounter
    assert record is not None
    wall_id = operation["wall_id"]
    if wall_id not in record["structure_ids"] or wall_id not in spatial["structures"]:
        raise ValueError("Shift Wall requires a live wall owned by the Architect")
    old = spatial["structures"][wall_id]
    start, end = operation["start"], operation["end"]
    if combat_spatial.distance(old["start"], start) > 30:
        raise ValueError("Shift Wall can move a wall at most 30 feet")
    if any(
        not isclose(start[axis] - old["start"][axis], end[axis] - old["end"][axis], abs_tol=1e-9)
        for axis in ("x", "y", "z")
    ):
        raise ValueError("Shift Wall must translate the section without reshaping it")
    combat_structures.move_wall(state, wall_id, start, end)
    return {"kind": "move_wall", "section_id": wall_id}


async def _floor_target(
    session: SessionData,
    state: CombatState,
    actor: CombatParticipant,
    target_id: str,
    section_id: str,
    steps: dict,
    progress: PacketRolls | None,
    deps: dict,
) -> dict | None:
    target = state.get_participant(target_id)
    assert target is not None
    if "save_success" not in steps:
        save = await packet_save(
            progress,
            session,
            target_id,
            "Reshape floor",
            partial(check_resolution_save.roll_participant_save, target, "DEX", 15, "Reshape floor"),
        )
        if save is None:
            return None
        steps["save_success"] = save.success
    effect = {"target_id": target_id, "save_success": steps["save_success"], "save_dc": 15}
    if effect["save_success"]:
        return effect
    resumed = "damage_receipt" in steps
    landed = await apply_attack_result(
        session,
        actor,
        {"name": "Reshape floor"},
        target,
        None if resumed else AutomaticDamageResult(dice.roll("2d6").total, "bludgeoning", context="reshape_floor"),
        target.ac,
        combat_state=state,
        publish_roll=False,
        progress=progress,
        **deps,
    )
    if progress is not None and progress.paused:
        return None
    record = state.architect_encounter
    assert record is not None
    record["pits"][target_id] = section_id
    effect.update(landed)
    effect["prone"] = _land_condition_on_one(state, target_id, actor, "prone", "Reshape floor", packet=effect)
    return effect


async def resolve_operation(
    session: SessionData,
    state: CombatState,
    actor: CombatParticipant,
    receipt: dict,
    *,
    progress: PacketRolls | None,
    damage_deps: dict,
) -> bool:
    """Finish a placed section's effects, independently of its action cost."""
    if receipt["kind"] != "open_floor":
        return True
    results = receipt["results"]
    for index, target_id in enumerate(receipt["targets"][len(results) :], start=len(results)):
        key = str(index)
        scope = progress.scope(key) if progress is not None else None
        result = await _floor_target(
            session,
            state,
            actor,
            target_id,
            receipt["section_id"],
            scope.steps if scope is not None else {},
            scope,
            damage_deps,
        )
        if result is None:
            return False
        results.append(result)
        if progress is not None:
            del progress.steps[key]
    return True


async def resolve(
    session: SessionData,
    state: CombatState,
    actor: CombatParticipant,
    operations: list[dict],
    receipts: list[dict],
    *,
    progress: PacketRolls | None,
    packet_deps: dict,
    legendary_kind: str | None = None,
) -> bool:
    """Resolve the section effects and resume any held floor saves."""
    record = state.architect_encounter
    assert record is not None
    damage_deps = {
        key: packet_deps[key]
        for key in ("mutations", "queries", "conn", "sink", "concentration_break_mod")
        if key in packet_deps
    }
    for index, op in enumerate(operations):
        if index == len(receipts):
            receipts.append(place_section(state, actor.id, op, shift_wall=legendary_kind == "shift_wall"))
            if legendary_kind is None:
                record["reshape_count"] = (
                    record["reshape_count"] + 1 if record["reshape_round"] == state.round_number else 1
                )
                record["reshape_round"] = state.round_number
        key = str(index)
        scope = progress.scope(key) if progress is not None and op["kind"] == "open_floor" else None
        if not await resolve_operation(session, state, actor, receipts[index], progress=scope, damage_deps=damage_deps):
            return False
        if scope is not None:
            assert progress is not None
            del progress.steps[key]
        if actor.is_fallen:
            return True
    return True
