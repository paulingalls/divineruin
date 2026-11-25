"""Movement expenditure along a straight segment through double-cost areas."""

import math

from combat_spatial import distance, mapping, number, point

AXES = ("x", "y", "z")
TIDEWALKER_KINDS = {"water", "mud", "architect_domain"}


def rectangle(low: dict, high: dict) -> tuple[dict, dict]:
    low, high = point(low), point(high)
    if low["z"] != high["z"] or any(low[axis] >= high[axis] for axis in ("x", "y")):
        raise ValueError("A rectangular section needs positive x and y dimensions at one height")
    return low, high


def validate_areas(value: object, actor_ids: list[str]) -> None:
    for area in mapping(value, "movement areas").values():
        common = {"kind", "excluded_actor_ids", "shape"}
        if not isinstance(area, dict):
            raise ValueError("Invalid movement area")
        shape = area.get("shape")
        if shape == "sphere" and set(area) == common | {"center", "radius_ft"}:
            point(area["center"])
            if number(area["radius_ft"], "area radius", nonnegative=True) == 0:
                raise ValueError("Movement area radius must be positive")
        elif shape == "rectangle" and set(area) == common | {"min", "max"}:
            rectangle(area["min"], area["max"])
        else:
            raise ValueError("Invalid movement area shape")
        kind = area["kind"]
        excluded = area["excluded_actor_ids"]
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError("Movement area requires a kind")
        if (
            not isinstance(excluded, list)
            or any(not isinstance(actor, str) or actor not in actor_ids for actor in excluded)
            or len(set(excluded)) != len(excluded)
        ):
            raise ValueError("Invalid movement area exclusions")


def _interval(area: dict, origin: dict, destination: dict) -> tuple[float, float] | None:
    delta = {axis: destination[axis] - origin[axis] for axis in AXES}
    if area["shape"] == "sphere":
        offset = {axis: area["center"][axis] - origin[axis] for axis in AXES}
        speed_sq = sum(d**2 for d in delta.values())
        if not speed_sq:
            return None
        mid = sum(delta[axis] * offset[axis] for axis in AXES) / speed_sq
        closest_sq = sum((offset[axis] - mid * delta[axis]) ** 2 for axis in AXES)
        remaining = area["radius_ft"] ** 2 - closest_sq
        if remaining <= 0:
            return None
        width = math.sqrt(remaining / speed_sq)
        return max(0.0, mid - width), min(1.0, mid + width)

    enter, leave = 0.0, 1.0
    for axis in ("x", "y"):
        low, high = area["min"][axis], area["max"][axis]
        if delta[axis]:
            a, b = sorted(((low - origin[axis]) / delta[axis], (high - origin[axis]) / delta[axis]))
            enter, leave = max(enter, a), min(leave, b)
        elif not low <= origin[axis] <= high:
            return None
    return enter, leave


def _covered(
    spatial: dict, actor_id: str, origin: dict, destination: dict, *, kind: str | None = None, tidewalker: bool = False
) -> list[tuple[float, float]]:
    return sorted(
        interval
        for area in spatial.get("movement_areas", {}).values()
        if actor_id not in area["excluded_actor_ids"]
        and (kind is None or area["kind"] == kind)
        and not (tidewalker and area["kind"] in TIDEWALKER_KINDS)
        and (interval := _interval(area, origin, destination)) is not None
        and interval[0] < interval[1]
    )


def crosses_low_ceiling(spatial: dict, actor_id: str, origin: dict, destination: dict) -> bool:
    return origin != destination and bool(_covered(spatial, actor_id, origin, destination, kind="low_ceiling"))


def _union(
    spatial: dict, actor_id: str, origin: dict, destination: dict, *, tidewalker: bool
) -> list[tuple[float, float]]:
    intervals: list[tuple[float, float]] = []
    for start, end in _covered(spatial, actor_id, origin, destination, tidewalker=tidewalker):
        if intervals and start <= intervals[-1][1]:
            previous, stop = intervals[-1]
            intervals[-1] = previous, max(stop, end)
        else:
            intervals.append((start, end))
    return intervals


def movement_cost(spatial: dict, actor_id: str, origin: dict, destination: dict, *, tidewalker: bool) -> float:
    length = distance(origin, destination)
    return length * (
        1 + sum(end - start for start, end in _union(spatial, actor_id, origin, destination, tidewalker=tidewalker))
    )


def reachable_point(
    spatial: dict, actor_id: str, origin: dict, destination: dict, allowance: float, *, tidewalker: bool
) -> dict:
    length = distance(origin, destination)
    if not length:
        return destination
    remaining = allowance / length
    previous = 0.0
    for start, end in _union(spatial, actor_id, origin, destination, tidewalker=tidewalker):
        if remaining <= start - previous:
            break
        remaining -= start - previous
        previous = start
        if remaining <= 2 * (end - start):
            remaining /= 2
            break
        remaining -= 2 * (end - start)
        previous = end
    fraction = min(1.0, previous + remaining)
    if fraction == 1 and movement_cost(spatial, actor_id, origin, destination, tidewalker=tidewalker) <= allowance:
        return destination
    end = {axis: origin[axis] + fraction * (destination[axis] - origin[axis]) for axis in AXES}
    # Interpolation can round beyond the available allowance.
    while movement_cost(spatial, actor_id, origin, end, tidewalker=tidewalker) > allowance:
        end = {axis: math.nextafter(end[axis], origin[axis]) for axis in AXES}
    return end
