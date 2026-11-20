"""Intercept the first ranged strike or spell at the Architect each round."""

from dataclasses import replace
from fractions import Fraction
from math import hypot, inf, nextafter
from typing import TypedDict

import combat_spatial
import combat_structures
from check_resolution_attack import _is_ranged
from combat_participant import CombatParticipant
from combat_state import CombatState
from declarations import Declaration
from spells import Spell


class Interception(TypedDict):
    target_id: str
    wall_id: str
    round: int
    redirected: bool
    cue: str


def _wall_prefix(owner_id: str) -> str:
    return f"{owner_id}_reaction_wall_"


def expire_walls(state: CombatState) -> None:
    record = state.architect_encounter
    if record is None:
        return
    prefix = _wall_prefix(record["owner_id"])
    reaction_ids = {wall_id for wall_id in record["structure_ids"] if wall_id.startswith(prefix)}
    for wall in state.participants:
        if wall.id in reaction_ids and not wall.is_dead:
            combat_structures.collapse_wall(state, wall)


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
    # Float endpoint rounding can put an inclined shot just below the exact wall floor.
    if not combat_structures.blocks_path(origin, target, {"start": start, "end": end}):
        crossing = combat_structures._intersection_interval(origin, target, {"start": start, "end": end})
        if crossing is None:
            raise ValueError("Reaction wall misses the incoming attack line")
        contact_z = Fraction(origin["z"]) + crossing[0] * (Fraction(target["z"]) - Fraction(origin["z"]))
        start["z"] = end["z"] = nextafter(float(contact_z), -inf)
    wall_id = f"{_wall_prefix(owner_id)}{state.round_number}"
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
    if receipt is None:
        if index and (
            wall := combat_structures.line_blocker(state, attacker.id, target.id, melee=not _is_ranged(action))
        ):
            return target, {"resolved": False, "reason": combat_structures.blocked_reason(wall)}
        if not _is_ranged(action):
            return target, {}
        receipt = _raise_wall(state, attacker, target.id, redirect=True)
        if receipt is None:
            return target, {}
        cursor["reactive_architecture"] = receipt
    wall = state.get_participant(receipt["wall_id"])
    if wall is None:
        raise ValueError(f"Missing reaction wall {receipt['wall_id']}")
    return wall, {"reactive_architecture": receipt}


def spell_targets(
    state: CombatState,
    attacker: CombatParticipant,
    decl: Declaration,
    spell: Spell,
    deliveries: list[dict] | None,
    steps: dict,
) -> tuple[Declaration | None, list[dict] | None, Interception | None]:
    receipt = steps.get("reactive_architecture")
    if receipt is None:
        targets = (
            [delivery["target_id"] for delivery in deliveries]
            if deliveries is not None
            else decl.target_ids or [decl.target_id]
        )
        attack = spell.combat_damage is not None and spell.combat_damage["resolution"] == "attack"
        for target_id in dict.fromkeys(targets):
            if (receipt := _raise_wall(state, attacker, target_id, redirect=attack)) is not None:
                steps["reactive_architecture"] = receipt
                break
    if receipt is None:
        return decl, deliveries, None

    if deliveries is not None:
        projected = [
            {**delivery, "target_id": effective}
            for delivery in deliveries
            if (effective := _effective_target(receipt, delivery["target_id"])) is not None
        ]
        return decl, projected, receipt
    if decl.target_ids:
        ids = [effective for target in decl.target_ids if (effective := _effective_target(receipt, target)) is not None]
        landing = replace(decl, target_ids=ids) if ids else None
    else:
        target = _effective_target(receipt, decl.target_id)
        landing = replace(decl, target_id=target) if target is not None else None
    return landing, None, receipt


def _effective_target(receipt: Interception, target_id: str | None) -> str | None:
    if target_id != receipt["target_id"]:
        return target_id
    return receipt["wall_id"] if receipt["redirected"] else None
