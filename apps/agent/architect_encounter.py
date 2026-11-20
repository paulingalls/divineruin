"""Own the Architect and its structures in combat."""

from __future__ import annotations

from typing import TYPE_CHECKING

import combat_spatial
import combat_structures
from combat_movement_cost import rectangle

if TYPE_CHECKING:
    from combat_state import CombatState

CREATURE_ID = "hollow_architect"
CONSTRUCT_SLAM = "Construct Slam"


def is_owner(state: CombatState, actor_id: str) -> bool:
    record = state.architect_encounter
    return record is not None and record["owner_id"] == actor_id


def initialize(state: CombatState) -> None:
    owner = next((p for p in state.participants if p.creature_id == CREATURE_ID), None)
    if owner is None:
        return
    spatial = combat_spatial.require_spatial(state)
    origin = combat_spatial.position(spatial, owner.id)
    structure_ids = []
    for label, offset in (("north", 10), ("south", -10)):
        wall_id = f"{owner.id}_wall_{label}"
        start = {**origin, "y": origin["y"] + offset}
        end = {**start, "x": start["x"] + 20}
        combat_structures.add_wall(state, wall_id, f"Architect's {label} wall", start, end)
        structure_ids.append(wall_id)
    assert owner.hollow is not None
    spatial.setdefault("movement_areas", {})[f"{owner.id}_domain"] = {
        "kind": "architect_domain",
        "shape": "sphere",
        "center": dict(origin),
        "radius_ft": owner.hollow["corruption_aura"],
        "excluded_actor_ids": [owner.id],
    }
    state.architect_encounter = {
        "owner_id": owner.id,
        "structure_ids": structure_ids,
        "phase": "active",
        "reshape_round": 0,
        "reaction_round": 0,
        "reshape_count": 0,
        "floors": {},
        "pits": {},
    }
    validate(state)


def validate(state: CombatState) -> None:
    record = state.architect_encounter
    owners = [p for p in state.participants if p.creature_id == CREATURE_ID]
    if record is None:
        if owners or state.encounter_id == CREATURE_ID:
            raise ValueError("Architect snapshot is missing its encounter record")
        return
    if not isinstance(record, dict) or set(record) != {
        "owner_id",
        "structure_ids",
        "phase",
        "reshape_round",
        "reaction_round",
        "reshape_count",
        "floors",
        "pits",
    }:
        raise ValueError("Invalid Architect encounter record")
    if len(owners) != 1 or owners[0].id != record["owner_id"] or owners[0].type != "enemy":
        raise ValueError("Architect encounter requires exactly one matching enemy owner")
    if sum(p.id == record["owner_id"] for p in state.participants) != 1:
        raise ValueError("Architect owner participant ID must be unique")
    ids = record["structure_ids"]
    if not isinstance(ids, list) or not ids or any(not isinstance(wall_id, str) for wall_id in ids):
        raise ValueError("Invalid Architect structure IDs")
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate Architect structure IDs")
    walls = {p.id: p for p in state.participants if p.is_structure}
    if any(wall_id not in walls for wall_id in ids):
        raise ValueError("Architect structure ID must identify a structure participant")
    expected_phase = "destroyed" if owners[0].hp_current <= 0 else "active"
    if record["phase"] != expected_phase:
        raise ValueError("Architect phase disagrees with owner HP")
    if expected_phase == "destroyed" and any(not walls[wall_id].is_dead for wall_id in ids):
        raise ValueError("Destroyed Architect still owns live walls")

    round_number, count = record["reshape_round"], record["reshape_count"]
    if (
        type(count) is not int
        or type(round_number) is not int
        or not ((round_number, count) == (0, 0) or (1 <= round_number <= state.round_number and 1 <= count <= 2))
    ):
        raise ValueError("Invalid Architect Reshape budget")
    reaction_round = record["reaction_round"]
    if type(reaction_round) is not int or not 0 <= reaction_round <= state.round_number:
        raise ValueError("Invalid Architect reaction round")
    spatial = combat_spatial.require_spatial(state)
    areas = spatial.get("movement_areas", {})
    domains = [area for area in areas.values() if area["kind"] == "architect_domain"]
    hollow = owners[0].hollow
    if (
        len(domains) != 1
        or hollow is None
        or domains[0]["shape"] != "sphere"
        or domains[0]["excluded_actor_ids"] != [record["owner_id"]]
        or domains[0]["radius_ft"] != hollow["corruption_aura"]
    ):
        raise ValueError("Invalid Architect domain")
    floors = combat_spatial.mapping(record["floors"], "Architect floors")
    for floor in floors.values():
        if not isinstance(floor, dict) or set(floor) != {"min", "max"}:
            raise ValueError("Invalid Architect floor")
        _check_section(floor)
    for area in areas.values():
        if area["kind"] == "low_ceiling":
            if area["shape"] != "rectangle" or area["excluded_actor_ids"]:
                raise ValueError("Invalid Architect ceiling")
            _check_section(area)
    pits = combat_spatial.mapping(record["pits"], "Architect pits")
    if any(
        actor_id not in spatial["positions"] or actor_id in walls or not isinstance(floor, str) or floor not in floors
        for actor_id, floor in pits.items()
    ):
        raise ValueError("Invalid Architect pit membership")
    _validate_receipts(state, record, areas)


def _check_section(section: dict) -> None:
    low, high = rectangle(section["min"], section["max"])
    if any(high[axis] - low[axis] > 20 for axis in ("x", "y")):
        raise ValueError("Invalid Architect section dimensions")


def _validate_receipts(state: CombatState, record: dict, areas: dict) -> None:
    from declarations import resolve_declaration

    for head in state.held_actions:
        steps = head.get("roll_steps", {})
        if not isinstance(steps, dict):
            raise ValueError("Invalid Architect held roll steps")
        checkpoints = steps.get("reshape", {})
        if "reshape_receipts" not in head and "reshape" not in head["declaration"] and not checkpoints:
            continue
        operations = resolve_declaration(head["declaration"]).reshape or []
        if not operations:
            if "reshape_receipts" in head or checkpoints:
                raise ValueError("Architect Reshape receipt has no declaration")
            continue
        receipts = head.get("reshape_receipts", [])
        if (
            head["actor_id"] != record["owner_id"]
            or not isinstance(receipts, list)
            or len(receipts) > len(operations)
            or (
                receipts
                and "legendary_kind" not in head
                and (record["reshape_round"] != state.round_number or len(receipts) > record["reshape_count"])
            )
        ):
            raise ValueError("Invalid Architect Reshape receipts")
        pending_floor = None
        for index, (operation, receipt) in enumerate(zip(operations[: len(receipts)], receipts, strict=True)):
            if not isinstance(receipt, dict) or receipt.get("kind") != operation["kind"]:
                raise ValueError("Invalid Architect Reshape operation receipt")
            kind, section_id = receipt["kind"], receipt.get("section_id")
            sections = {"open_floor": record["floors"], "lower_ceiling": areas}.get(kind, record["structure_ids"])
            if not isinstance(section_id, str) or section_id not in sections:
                raise ValueError("Invalid Architect Reshape receipt section")
            if kind in ("move_wall", "destroy_wall") and section_id != operation["wall_id"]:
                raise ValueError("Invalid Architect Reshape wall receipt")
            if kind in ("open_floor", "lower_ceiling"):
                section = sections[section_id]
                if kind == "lower_ceiling" and section["kind"] != "low_ceiling":
                    raise ValueError("Invalid Architect Reshape ceiling receipt")
                if any(section[corner] != operation[corner] for corner in ("min", "max")):
                    raise ValueError("Invalid Architect Reshape footprint receipt")
            fields = {"kind", "section_id"}
            if kind == "open_floor":
                fields |= {"targets", "results"}
                targets, results = receipt.get("targets"), receipt.get("results")
                if (
                    not isinstance(targets, list)
                    or not isinstance(results, list)
                    or any(not isinstance(target, str) or state.get_participant(target) is None for target in targets)
                    or len(set(targets)) != len(targets)
                    or len(results) > len(targets)
                    or (index < len(receipts) - 1 and len(results) != len(targets))
                    or any(
                        not isinstance(result, dict)
                        or result.get("target_id") != target
                        or type(result.get("save_success")) is not bool
                        for target, result in zip(targets[: len(results)], results, strict=True)
                    )
                ):
                    raise ValueError("Invalid Architect Reshape floor receipt")
                if len(results) < len(targets):
                    pending_floor = str(index), str(len(results))
            if set(receipt) != fields:
                raise ValueError("Invalid Architect Reshape receipt fields")
        _validate_floor_checkpoint(checkpoints, pending_floor)


def _validate_floor_checkpoint(checkpoints: object, pending_floor: tuple[str, str] | None) -> None:
    from combat_fate_rolls import saved_throw

    if not isinstance(checkpoints, dict) or set(checkpoints) != ({pending_floor[0]} if pending_floor else set()):
        raise ValueError("Invalid Architect Reshape floor checkpoint")
    if pending_floor is None:
        return
    section, target = pending_floor
    targets = checkpoints[section]
    if not isinstance(targets, dict) or set(targets) != {target}:
        raise ValueError("Invalid Architect Reshape target checkpoint")
    step = targets[target]
    if isinstance(step, dict):
        if set(step) == {"save"}:
            try:
                saved_throw(step["save"])
            except (TypeError, KeyError, ValueError) as error:
                raise ValueError("Invalid Architect Reshape saved throw") from error
            return
        if step.get("save_success") is False and isinstance(step.get("damage_receipt"), dict):
            return
    raise ValueError("Invalid Architect Reshape floor checkpoint")


def facts(state: CombatState) -> dict | None:
    record = state.architect_encounter
    if record is None:
        return None
    owner = state.get_participant(record["owner_id"])
    assert owner is not None
    from architect_reshape import remaining

    spatial = combat_spatial.require_spatial(state)
    live_segments = spatial["structures"]
    live_walls = [wall_id for wall_id in record["structure_ids"] if wall_id in live_segments]
    details = {
        **{key: value for key, value in record.items() if key != "reaction_round"},
        "hp": owner.hp_current,
        "live_wall_ids": live_walls,
        "live_walls": {wall_id: live_segments[wall_id] for wall_id in live_walls},
        "legendary": {
            **owner.legendary,
            "remaining": owner.legendary_actions,
        }
        if owner.legendary is not None
        else None,
        "reshape_uses_remaining": remaining(state, owner) if record["phase"] == "active" else 0,
        "reshape": "Create, move or destroy a wall, open a floor or lower a ceiling. "
        "Sections are up to 20 feet across and within 120 feet. "
        "A failed floor save knocks its target prone into a pit. Climbing out costs a full move. "
        "Low ceilings slow movement and block flight.",
        "movement_areas": spatial["movement_areas"],
    }
    if record["phase"] == "destroyed":
        details["cue"] = owner.catalog_narration["death_cue"]
    return details


def destroyed(state: CombatState) -> None:
    record = state.architect_encounter
    assert record is not None
    record["phase"] = "destroyed"
    for wall_id in record["structure_ids"]:
        wall = state.get_participant(wall_id)
        assert wall is not None
        if not wall.is_dead:
            combat_structures.collapse_wall(state, wall)
