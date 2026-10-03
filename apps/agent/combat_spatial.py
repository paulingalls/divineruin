"""JSON-native combat geometry in feet."""

import math
from copy import deepcopy


def number(value, label, *, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label}: expected finite number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or (nonnegative and value < 0):
        raise ValueError(
            f"{label}: expected finite nonnegative number" if nonnegative else f"{label}: expected finite number"
        )
    return value


def point(value):
    if not isinstance(value, dict) or set(value) != {"x", "y", "z"}:
        raise ValueError("point requires x, y, z")
    return {axis: number(value[axis], axis) for axis in ("x", "y", "z")}


def distance(left, right):
    a, b = point(left), point(right)
    return number(math.dist(tuple(a.values()), tuple(b.values())), "distance", nonnegative=True)


def inside(left, right, radius_ft):
    return distance(left, right) <= number(radius_ft, "radius", nonnegative=True)


def mapping(value, label):
    if not isinstance(value, dict) or any(not isinstance(key, str) or not key.strip() for key in value):
        raise ValueError(f"{label}: expected map with nonempty IDs")
    return value


def validate_maps(positions, locations, zones):
    for label, points in (("positions", positions), ("locations", locations)):
        for value in mapping(points, label).values():
            point(value)
    points = [*positions.values(), *locations.values()]
    for left in points:
        for right in points:
            distance(left, right)
    for zone in mapping(zones, "zones").values():
        if not isinstance(zone, dict) or set(zone) not in (
            {"center_id", "radius_ft"},
            {"kind", "center_id", "radius_ft"},
        ):
            raise ValueError("zone requires center_id and radius_ft, optionally kind=silence")
        if "kind" in zone and zone["kind"] != "silence":
            raise ValueError("zone kind must be silence")
        center = zone["center_id"]
        if not isinstance(center, str) or center not in positions.keys() | locations.keys():
            raise ValueError("unknown zone center")
        number(zone["radius_ft"], "radius", nonnegative=True)
    ids = [*positions, *locations, *zones]
    if len(ids) != len(set(ids)):
        raise ValueError("spatial IDs must be unique")


def validate_scene(encounter):
    scene = encounter.get("scene_placement")
    if not isinstance(scene, dict) or set(scene) != {"party_start", "companion_start", "actors", "locations", "zones"}:
        raise ValueError("scene_placement requires explicit starts, actors, locations and zones")
    point(scene["party_start"])
    point(scene["companion_start"])
    enemies = encounter["enemies"]
    ids = [enemy["id"] for enemy in enemies]
    if len(ids) != len(set(ids)) or set(mapping(scene["actors"], "actors")) != set(ids):
        raise ValueError("scene_placement must cover every enemy exactly")
    validate_maps(scene["actors"], scene["locations"], scene["zones"])
    for start in (scene["party_start"], scene["companion_start"]):
        for other in [
            scene["party_start"],
            scene["companion_start"],
            *scene["actors"].values(),
            *scene["locations"].values(),
        ]:
            distance(start, other)
    return deepcopy(scene)


def validate_spatial(spatial, actor_ids):
    if not isinstance(spatial, dict) or set(spatial) != {"positions", "locations", "zones", "speeds"}:
        raise ValueError("invalid persisted spatial record")
    validate_maps(spatial["positions"], spatial["locations"], spatial["zones"])
    speeds = mapping(spatial["speeds"], "speeds")
    if set(spatial["positions"]) != set(actor_ids) or set(speeds) != set(actor_ids):
        raise ValueError("spatial record must cover every actor")
    for value in speeds.values():
        number(value, "speed", nonnegative=True)
    return deepcopy(spatial)


def require_spatial(state):
    if state is None or state.spatial is None:
        raise ValueError("Combat has no committed spatial placement")
    validate_spatial(state.spatial, [p.id for p in state.participants])
    return state.spatial


def position(spatial, target_id):
    if target_id in spatial["positions"]:
        return point(spatial["positions"][target_id])
    if target_id in spatial["locations"]:
        return point(spatial["locations"][target_id])
    raise ValueError(f"Unknown position {target_id!r}")


def facts(state, origin_id):
    spatial = require_spatial(state)
    origin = position(spatial, origin_id)
    distances = {
        key: distance(origin, position(spatial, key)) for key in sorted([*spatial["positions"], *spatial["locations"]])
    }
    inactive_auras = {
        f"{actor.id}_corruption_aura"
        for actor in state.participants
        if actor.hollow is not None and (actor.is_dead or actor.is_fallen or actor.hp_current <= 0)
    }
    zones = {
        key: {
            **zone,
            "center": position(spatial, zone["center_id"]),
            "members": [
                actor_id
                for actor_id, pos in sorted(spatial["positions"].items())
                if inside(pos, position(spatial, zone["center_id"]), zone["radius_ft"])
            ],
        }
        for key, zone in spatial["zones"].items()
        if key not in inactive_auras
    }
    return {
        "origin_id": origin_id,
        "positions": deepcopy(spatial["positions"]),
        "locations": deepcopy(spatial["locations"]),
        "zones": zones,
        "distances_ft": distances,
        "speeds_ft": deepcopy(spatial["speeds"]),
        "spoken": [f"{key} is {value:g} feet from {origin_id}" for key, value in distances.items() if key != origin_id],
    }


def response_facts(state, acting_id, primary_id):
    if state.spatial is None:
        return None
    # A member who joined mid-fight has no position; the session owner entered with the party.
    return facts(state, acting_id if acting_id in state.spatial["positions"] else primary_id)
