"""Runtime wall participants and their spatial segments."""

from __future__ import annotations

from fractions import Fraction
from typing import TYPE_CHECKING, TypedDict

from combat_participant import CombatParticipant
from combat_spatial import distance, mapping, point, require_spatial

if TYPE_CHECKING:
    from combat_state import CombatState

Point = dict[str, int | float]
Vector = tuple[Fraction, Fraction]
WALL_AC = 19
WALL_HP = 30


class Segment(TypedDict):
    start: Point
    end: Point


def _segment(value: object) -> Segment:
    if not isinstance(value, dict) or set(value) != {"start", "end"}:
        raise ValueError("structure segment requires start and end")
    start, end = point(value["start"]), point(value["end"])
    if (start["x"], start["y"]) == (end["x"], end["y"]):
        raise ValueError("structure segment requires horizontal extent")
    return {"start": start, "end": end}


def validate_segments(value: object) -> None:
    for segment in mapping(value, "structures").values():
        _segment(segment)


def add_wall(state: CombatState, wall_id: str, name: str, start: Point, end: Point) -> CombatParticipant:
    spatial = require_spatial(state)
    segment = _segment({"start": start, "end": end})
    if not isinstance(wall_id, str) or not wall_id.strip():
        raise ValueError("structure requires a nonempty ID")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("structure requires a nonempty name")
    if any(wall_id in spatial[key] for key in ("positions", "locations", "zones")) or wall_id in state.initiative_order:
        raise ValueError(f"Duplicate spatial ID {wall_id!r}")
    start, end = segment["start"], segment["end"]
    center = {"x": start["x"] / 2 + end["x"] / 2, "y": start["y"] / 2 + end["y"] / 2, "z": min(start["z"], end["z"])}
    for other in (*spatial["positions"].values(), *spatial["locations"].values()):
        distance(center, other)

    wall = CombatParticipant(
        id=wall_id, name=name, type="structure", initiative=0, hp_current=WALL_HP, hp_max=WALL_HP, ac=WALL_AC
    )
    state.participants.append(wall)
    spatial["positions"][wall_id] = center
    spatial["speeds"][wall_id] = 0
    spatial.setdefault("structures", {})[wall_id] = segment
    return wall


def validate_participants(state: CombatState) -> None:
    walls = [p for p in state.participants if p.is_structure]
    spatial = state.spatial
    if spatial is None:
        if walls:
            raise ValueError("structure requires spatial placement")
        return
    wall_ids = {wall.id for wall in walls}
    if wall_ids and sum(p.id in wall_ids for p in state.participants) != len(wall_ids):
        raise ValueError("structures require a unique participant ID")
    live_ids = set()
    for wall in walls:
        label = f"{wall.name} ({wall.id})"
        if spatial["speeds"][wall.id] != 0:
            raise ValueError(f"{label}: invalid structure speed")
        if (wall.ac, wall.hp_max) != (WALL_AC, WALL_HP):
            raise ValueError(f"{label}: invalid structure stats")
        if wall.is_fallen or wall.is_dead:
            if (wall.is_fallen, wall.is_dead, wall.hp_current) != (True, True, 0):
                raise ValueError(f"{label}: invalid destroyed structure")
        else:
            if type(wall.hp_current) is not int or not 0 < wall.hp_current <= WALL_HP:
                raise ValueError(f"{label}: invalid live structure HP")
            live_ids.add(wall.id)
    if set(spatial.get("structures", {})) != live_ids:
        raise ValueError("structure segments must identify exactly the live structures")


def _xy_delta(origin: Point, end: Point) -> Vector:
    return Fraction(end["x"]) - Fraction(origin["x"]), Fraction(end["y"]) - Fraction(origin["y"])


def _cross(left: Vector, right: Vector) -> Fraction:
    return left[0] * right[1] - left[1] * right[0]


def _intersection_interval(origin: Point, destination: Point, wall: Segment) -> tuple[Fraction, Fraction] | None:
    # Exact arithmetic keeps boundary contacts closed even for nearly parallel paths.
    path = _xy_delta(origin, destination)
    edge = _xy_delta(wall["start"], wall["end"])
    offset = _xy_delta(origin, wall["start"])
    determinant = _cross(path, edge)
    if determinant:
        path_t = _cross(offset, edge) / determinant
        wall_t = _cross(offset, path) / determinant
        if 0 <= path_t <= 1 and 0 <= wall_t <= 1:
            return path_t, path_t
        return None

    if _cross(offset, edge):
        return None
    axis = 0 if edge[0] else 1
    if not path[axis]:
        if 0 <= -offset[axis] / edge[axis] <= 1:
            return Fraction(0), Fraction(1)
        return None

    start_t, end_t = sorted((offset[axis] / path[axis], (offset[axis] + edge[axis]) / path[axis]))
    lo, hi = max(Fraction(0), start_t), min(Fraction(1), end_t)
    return (lo, hi) if lo <= hi else None


def blocks_path(origin: Point, destination: Point, wall: Segment) -> bool:
    interval = _intersection_interval(origin, destination, wall)
    if interval is None:
        return False
    z = Fraction(origin["z"])
    dz = Fraction(destination["z"]) - z
    z_start, z_end = (z + t * dz for t in interval)
    floor = Fraction(min(wall["start"]["z"], wall["end"]["z"]))
    return max(z_start, z_end) >= floor and min(z_start, z_end) <= floor + 20


def blocking_wall(state: CombatState, spatial: dict, origin: Point, destination: Point) -> CombatParticipant | None:
    for wall_id, segment in spatial.get("structures", {}).items():
        if blocks_path(origin, destination, segment):
            wall = state.get_participant(wall_id)
            if wall is None:
                raise ValueError(f"Unknown structure participant {wall_id!r}")
            return wall
    return None


def remove_wall_segment(state: CombatState | None, wall: CombatParticipant) -> None:
    if state is None or state.spatial is None:
        raise ValueError(f"{wall.name} ({wall.id}) requires spatial placement")
    del state.spatial["structures"][wall.id]
