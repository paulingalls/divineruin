"""Resolve authored starts to actual participant IDs before initiative."""

from copy import deepcopy

from combat_spatial import number, validate_scene, validate_spatial


def build_spatial(encounter, players, enemies, companion=None):
    scene = validate_scene(encounter)
    positions = deepcopy(scene["actors"])
    speeds = {enemy["id"]: number(enemy.get("speed"), "creature speed", nonnegative=True) for enemy in enemies}
    for actor_id, row in players:
        if actor_id in positions or not isinstance(row, dict):
            raise ValueError(f"invalid player {actor_id!r}")
        positions[actor_id] = deepcopy(scene["party_start"])
        speeds[actor_id] = number(row.get("speed"), f"{actor_id} speed", nonnegative=True)
    if companion is not None:
        actor_id, speed = companion
        if actor_id in positions:
            raise ValueError(f"duplicate companion {actor_id!r}")
        positions[actor_id] = deepcopy(scene["companion_start"])
        speeds[actor_id] = number(speed, "companion speed", nonnegative=True)
    spatial = {"positions": positions, "speeds": speeds, "locations": scene["locations"], "zones": scene["zones"]}
    return validate_spatial(spatial, list(positions))
