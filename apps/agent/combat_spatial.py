"""JSON-native combat geometry in feet."""

import math
from copy import deepcopy
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from combat_state import CombatState


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


def validate_maps(positions, locations, zones, *, zone_kinds, allow_smoke_expiry: bool = False):
    for label, points in (("positions", positions), ("locations", locations)):
        for value in mapping(points, label).values():
            point(value)
    points = [*positions.values(), *locations.values()]
    for left in points:
        for right in points:
            distance(left, right)
    zone_keys = [
        {"center_id", "radius_ft"},
        {"kind", "center_id", "radius_ft"},
    ]
    if allow_smoke_expiry:
        zone_keys.append({"kind", "center_id", "radius_ft", "expires_round"})
    for zone in mapping(zones, "zones").values():
        if not isinstance(zone, dict) or set(zone) not in zone_keys:
            raise ValueError("zone requires center_id and radius_ft, optionally kind")
        if "kind" in zone and zone["kind"] not in zone_kinds:
            raise ValueError(f"zone kind must be one of {', '.join(zone_kinds)}")
        center = zone["center_id"]
        if not isinstance(center, str) or center not in positions.keys() | locations.keys():
            raise ValueError("unknown zone center")
        number(zone["radius_ft"], "radius", nonnegative=True)
        if "expires_round" in zone:
            expiry = zone["expires_round"]
            if zone["kind"] != "smoke" or type(expiry) is not int or expiry <= 0 or center not in locations:
                raise ValueError("zone expiry requires smoke with a location center and a positive integer round")
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
    validate_maps(scene["actors"], scene["locations"], scene["zones"], zone_kinds=("silence", "smoke"))
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
    keys = {"positions", "locations", "zones", "speeds"}
    if not isinstance(spatial, dict) or not keys <= set(spatial) <= keys | {"structures", "movement_areas", "chambers"}:
        raise ValueError("invalid persisted spatial record")
    validate_maps(
        spatial["positions"],
        spatial["locations"],
        spatial["zones"],
        zone_kinds=("silence", "cathedral", "smoke"),
        allow_smoke_expiry=True,
    )
    speeds = mapping(spatial["speeds"], "speeds")
    if set(spatial["positions"]) != set(actor_ids) or set(speeds) != set(actor_ids):
        raise ValueError("spatial record must cover every actor")
    for value in speeds.values():
        number(value, "speed", nonnegative=True)
    if "structures" in spatial:
        from combat_structures import validate_segments

        validate_segments(spatial["structures"])
    if "chambers" in spatial:
        mapping(spatial["chambers"], "chambers")
    if "movement_areas" in spatial:
        from combat_movement_cost import validate_areas

        validate_areas(spatial["movement_areas"], actor_ids)
    return deepcopy(spatial)


def require_spatial(state):
    if state is None or state.spatial is None:
        raise ValueError("Combat has no committed spatial placement")
    from combat_structures import validate_participants

    validate_spatial(state.spatial, [p.id for p in state.participants])
    validate_participants(state)
    return state.spatial


def position(spatial, target_id):
    if target_id in spatial["positions"]:
        return point(spatial["positions"][target_id])
    if target_id in spatial["locations"]:
        return point(spatial["locations"][target_id])
    raise ValueError(f"Unknown position {target_id!r}")


def add_smoke(state: "CombatState", actor_id: str) -> str:
    spatial = require_spatial(state)
    cloud_id = f"smoke_{uuid4().hex}"
    center_id = f"{cloud_id}_origin"
    spatial["locations"][center_id] = position(spatial, actor_id)
    spatial["zones"][cloud_id] = {
        "kind": "smoke",
        "center_id": center_id,
        "radius_ft": 10,
        "expires_round": state.round_number + 1,
    }
    return cloud_id


def expire_smoke(state: "CombatState") -> None:
    if state.spatial is None:
        return
    zones = state.spatial["zones"]
    expired = [
        zone_id
        for zone_id, zone in zones.items()
        if "expires_round" in zone and zone["expires_round"] <= state.round_number
    ]
    expired_centers = {zones.pop(zone_id)["center_id"] for zone_id in expired}
    for center_id in expired_centers - {zone["center_id"] for zone in zones.values()}:
        del state.spatial["locations"][center_id]


def smoke_obscures(spatial: dict, attacker_id: str, target_id: str) -> bool:
    for zone in spatial["zones"].values():
        if zone.get("kind") != "smoke":
            continue
        center = position(spatial, zone["center_id"])
        if inside(position(spatial, attacker_id), center, zone["radius_ft"]) or inside(
            position(spatial, target_id), center, zone["radius_ft"]
        ):
            return True
    return False


def place(state, target_id, destination):
    spatial = require_spatial(state)
    if target_id not in spatial["positions"]:
        raise ValueError(f"Unknown participant position {target_id!r}")
    destination = point(destination)
    spatial["positions"][target_id] = destination
    if (record := state.architect_encounter) and (floor_id := record["pits"].get(target_id)):
        floor = record["floors"][floor_id]
        if any(not floor["min"][axis] <= destination[axis] <= floor["max"][axis] for axis in ("x", "y", "z")):
            del record["pits"][target_id]
    from architect_encounter import end_cathedral_after_move
    from choir_effects import exposure

    end_cathedral_after_move(state, target_id)
    exposure(state)
    return dict(spatial["positions"][target_id])


def force_place(state, target_id: str, destination: dict) -> dict:
    from condition_restrictions import immovable

    spatial = require_spatial(state)
    target = state.get_participant(target_id)
    if target is None or target_id not in spatial["positions"]:
        raise ValueError(f"Unknown participant position {target_id!r}")
    origin = position(spatial, target_id)
    destination = point(destination)
    if immovable(target.conditions):
        return {"destination": origin, "distance_ft": 0, "movement_blocked": "Iron Stance"}
    destination = place(state, target_id, destination)
    return {"destination": destination, "distance_ft": distance(origin, destination)}


def facts(state, origin_id):
    import architect_entomb
    from condition_restrictions import effective_speed

    spatial = require_spatial(state)
    origin = position(spatial, origin_id)
    retired = {p.id for p in state.participants if p.is_structure and p.is_dead}
    positions = {key: pos for key, pos in spatial["positions"].items() if key not in retired}
    distances = {key: distance(origin, position(spatial, key)) for key in sorted([*positions, *spatial["locations"]])}
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
                for actor_id, pos in sorted(positions.items())
                if inside(pos, position(spatial, zone["center_id"]), zone["radius_ft"])
            ],
        }
        for key, zone in spatial["zones"].items()
        if key not in inactive_auras
    }
    result = {
        "origin_id": origin_id,
        "positions": deepcopy(positions),
        "locations": deepcopy(spatial["locations"]),
        "zones": zones,
        "distances_ft": distances,
        "speeds_ft": {
            p.id: effective_speed(spatial["speeds"][p.id], p.conditions)
            for p in state.participants
            if p.id in positions
        },
        "spoken": [f"{key} is {value:g} feet from {origin_id}" for key, value in distances.items() if key != origin_id],
    }

    names = {actor.id: actor.name for actor in state.participants}
    for zone in zones.values():
        if zone.get("kind") == "smoke":
            zone["name"] = "Smoke cloud"
            members = ", ".join(names[actor_id] for actor_id in zone["members"]) or "no one"
            result["spoken"].append(f"Smoke cloud, {zone['radius_ft']:g} feet in radius. Inside: {members}.")

    if "movement_areas" in spatial:
        result["movement_areas"] = deepcopy(spatial["movement_areas"])

    from combat_structures import wall_facts

    walls, spoken = wall_facts(state, spatial)
    if walls:
        result["walls"] = walls
        result["spoken"].extend(spoken)
    chambers, spoken = architect_entomb.facts(state, spatial)
    if chambers:
        result["chambers"] = chambers
        result["spoken"].extend(spoken)
    return result


def response_facts(state, acting_id, primary_id):
    if state.spatial is None:
        return None
    # A member who joined mid-fight has no position; the session owner entered with the party.
    return facts(state, acting_id if acting_id in state.spatial["positions"] else primary_id)


def axis_projection(origin, aim, candidate):
    origin, aim, candidate = point(origin), point(aim), point(candidate)
    length = distance(origin, aim)
    if length == 0:
        raise ValueError("Area aim must differ from its source position")
    direction = [(aim[k] - origin[k]) / length for k in origin]
    offset = [candidate[k] - origin[k] for k in origin]
    axial = number(sum(a * b for a, b in zip(direction, offset, strict=True)), "axial distance")
    perpendicular = math.hypot(*(b - axial * a for a, b in zip(direction, offset, strict=True)))
    return axial, number(perpendicular, "perpendicular distance")


def in_line(origin, aim, candidate, length_ft, width_ft):
    axial, perpendicular = axis_projection(origin, aim, candidate)
    return (
        0 < axial <= number(length_ft, "length", nonnegative=True)
        and perpendicular <= number(width_ft, "width", nonnegative=True) / 2
    )


def in_cone(origin, aim, candidate, length_ft):
    axial, perpendicular = axis_projection(origin, aim, candidate)
    return 0 < axial <= number(length_ft, "length", nonnegative=True) and perpendicular <= axial / 2
