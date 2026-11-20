"""Own the Architect and its structures in combat."""

from __future__ import annotations

from typing import TYPE_CHECKING

import combat_spatial
import combat_structures

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
    state.architect_encounter = {"owner_id": owner.id, "structure_ids": structure_ids, "phase": "active"}
    validate(state)


def validate(state: CombatState) -> None:
    record = state.architect_encounter
    owners = [p for p in state.participants if p.creature_id == CREATURE_ID]
    if record is None:
        if owners or state.encounter_id == CREATURE_ID:
            raise ValueError("Architect snapshot is missing its encounter record")
        return
    if not isinstance(record, dict) or set(record) != {"owner_id", "structure_ids", "phase"}:
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


def facts(state: CombatState) -> dict | None:
    record = state.architect_encounter
    if record is None:
        return None
    owner = state.get_participant(record["owner_id"])
    assert owner is not None
    details = {**record, "hp": owner.hp_current}
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
