"""Intercept the first ranged strike or spell at the Architect each round."""

from math import hypot
from typing import TypedDict

import combat_spatial
import combat_structures
from check_resolution_attack import _is_ranged
from combat_participant import CombatParticipant
from combat_state import CombatState


class Interception(TypedDict):
    target_id: str
    wall_id: str
    round: int
    redirected: bool
    cue: str


def _raise_wall(
    state: CombatState, attacker: CombatParticipant, target_id: str | None, *, redirect: bool
) -> Interception | None:
    record = state.architect_encounter
    if record is None or target_id != record["owner_id"]:
        return None
    if record["phase"] != "active" or record["reaction_round"] == state.round_number:
        return None

    owner_id: str = record["owner_id"]
    spatial = combat_spatial.require_spatial(state)
    origin = combat_spatial.position(spatial, attacker.id)
    target = combat_spatial.position(spatial, owner_id)
    dx, dy = target["x"] - origin["x"], target["y"] - origin["y"]
    distance = hypot(dx, dy)
    across_x, across_y = (-10 * dy / distance, 10 * dx / distance) if distance else (10.0, 0.0)
    x, y, z = ((origin[axis] + target[axis]) / 2 for axis in ("x", "y", "z"))
    start = {"x": x - across_x, "y": y - across_y, "z": z}
    end = {"x": x + across_x, "y": y + across_y, "z": z}
    wall_id = f"{owner_id}_reaction_wall_{state.round_number}"
    combat_structures.add_wall(state, wall_id, "Architect's reaction wall", start, end)
    record["structure_ids"].append(wall_id)
    record["reaction_round"] = state.round_number
    effect = "The blow is aimed at the wall." if redirect else "The wall blocks the spell."
    return {
        "target_id": owner_id,
        "wall_id": wall_id,
        "round": state.round_number,
        "redirected": redirect,
        "cue": f"Reactive Architecture. Stone grinds up between the attacker and the Architect. {effect}",
    }


def weapon_target(
    state: CombatState,
    attacker: CombatParticipant,
    target: CombatParticipant,
    action: dict,
    cursor: dict,
    index: int,
) -> tuple[CombatParticipant, dict]:
    receipt = cursor.get("reactive_architecture")
    if receipt is not None:
        wall = state.get_participant(receipt["wall_id"])
        if wall is None:
            raise ValueError(f"Missing reaction wall {receipt['wall_id']}")
        return wall, {"reactive_architecture": receipt}
    if index and (wall := combat_structures.line_blocker(state, attacker.id, target.id, melee=not _is_ranged(action))):
        return target, {"resolved": False, "reason": combat_structures.blocked_reason(wall)}
    if _is_ranged(action) and (receipt := _raise_wall(state, attacker, target.id, redirect=True)):
        cursor["reactive_architecture"] = receipt
        wall = state.get_participant(receipt["wall_id"])
        assert wall is not None
        return wall, {"reactive_architecture": receipt}
    return target, {}
