"""Choir silence clocks and movement receipts live in the phase transaction."""

from copy import deepcopy
from uuid import uuid4

import combat_spatial
from condition_restrictions import cannot_act, speed_zero
from conditions import has_condition
from spell_voice_rules import is_silenced


def suppressed(actor):
    return (
        actor.creature_id == "hollow_choir"
        and actor.choir_suppression is not None
        and actor.choir_suppression["active"]
    )


def exposure(state):
    if state.spatial is None:
        return
    for actor in state.participants:
        if actor.creature_id != "hollow_choir":
            continue
        occupied = is_silenced(state, actor.id)
        if occupied and not actor.choir_silence_exposed:
            actor.choir_suppression = {"expires_round": state.round_number + 2, "active": True}
        actor.choir_silence_exposed = occupied


def inflict_silence(state, actor, action, declaration):
    spatial = combat_spatial.require_spatial(state)
    target = declaration.target_id or actor.id
    if state.get_participant(target) is None:
        raise ValueError("Silence Void requires a known participant center")
    center = combat_spatial.position(spatial, target)
    token = uuid4().hex
    location_id, zone_id = f"choir_center_{token}", f"choir_silence_{token}"
    spatial["locations"][location_id] = deepcopy(center)
    spatial["zones"][zone_id] = {"kind": "silence", "center_id": location_id, "radius_ft": action["radius_ft"]}
    state.choir_silences[zone_id] = {
        "source_id": actor.id,
        "center_id": location_id,
        "inflicted_round": state.round_number,
        "expires_round": state.round_number + action["rounds"] + 1,
    }
    exposure(state)
    return {"actor_id": actor.id, "resolved": True, "silence_zone": zone_id, "center": center}


def advance_round(state):
    for zone_id, effect in list(state.choir_silences.items()):
        if state.round_number >= effect["expires_round"]:
            spatial = combat_spatial.require_spatial(state)
            del spatial["zones"][zone_id]
            del spatial["locations"][effect["center_id"]]
            del state.choir_silences[zone_id]
    for actor in state.participants:
        if actor.choir_suppression is not None:
            actor.choir_suppression["active"] = state.round_number < actor.choir_suppression["expires_round"]
        if actor.creature_id == "hollow_choir" and state.spatial is not None:
            actor.choir_silence_exposed = is_silenced(state, actor.id)


def approach(state, actor):
    if (
        actor is None
        or actor.is_fallen
        or actor.is_dead
        or cannot_act(actor.conditions)
        or speed_zero(actor.conditions)
    ):
        return None
    if actor.choir_movement_round == state.round_number:
        return {"actor_id": actor.id, "resolved": True, "movement_consumed": True}
    charm = next((c for c in actor.conditions if c["type"] == "charmed" and c.get("choir_melody") is True), None)
    if charm is None:
        return None
    source = state.get_participant(charm["source"])
    if source is None:
        raise ValueError("Melody source is not a participant")
    spatial = combat_spatial.require_spatial(state)
    origin, voice = combat_spatial.position(spatial, actor.id), combat_spatial.position(spatial, source.id)
    distance = combat_spatial.distance(origin, voice)
    step = min(distance, spatial["speeds"][actor.id])
    if distance:
        spatial["positions"][actor.id] = {
            axis: origin[axis] + (voice[axis] - origin[axis]) * step / distance for axis in origin
        }
    actor.choir_movement_round = state.round_number
    exposure(state)
    return {
        "actor_id": actor.id,
        "resolved": True,
        "moved_ft": step,
        "destination": deepcopy(spatial["positions"][actor.id]),
        "forced_movement": True,
    }


def validate_data(data):
    from action_contracts import validate_action_extensions

    participants = {p["id"]: p for p in data["participants"]}
    round_number = data.get("round_number", 1)
    effects = data.get("choir_silences", {})
    if not isinstance(effects, dict):
        raise ValueError("invalid Choir silence effects")
    spatial = data.get("spatial")
    if spatial is not None and {key for key in spatial["zones"] if key.startswith("choir_silence_")} != set(effects):
        raise ValueError("Choir silence zone has no expiry owner")
    for zone_id, effect in effects.items():
        if not isinstance(effect, dict) or set(effect) != {
            "source_id",
            "center_id",
            "inflicted_round",
            "expires_round",
        }:
            raise ValueError("invalid Choir silence effect")
        if effect["source_id"] not in participants or spatial is None:
            raise ValueError("invalid Choir silence source/geometry")
        if any(type(effect[key]) is not int for key in ("inflicted_round", "expires_round")):
            raise ValueError("invalid Choir silence clock")
        if (
            effect["expires_round"] != effect["inflicted_round"] + 4
            or not 1 <= effect["inflicted_round"] <= round_number < effect["expires_round"]
        ):
            raise ValueError("invalid Choir silence expiry")
        zone = spatial["zones"].get(zone_id)
        if (
            zone is None
            or zone.get("kind") != "silence"
            or zone["center_id"] != effect["center_id"]
            or effect["center_id"] not in spatial["locations"]
        ):
            raise ValueError("invalid Choir silence reference")
    for actor in participants.values():
        reaction = actor.get("choir_reaction")
        if reaction is not None:
            if (
                actor.get("creature_id") != "hollow_choir"
                or not isinstance(reaction, dict)
                or reaction.get("kind") != "spell_redirect"
            ):
                raise ValueError("invalid Choir reaction owner")
            validate_action_extensions(reaction, "choir_reaction")
        if type(actor.get("choir_silence_exposed", False)) is not bool:
            raise ValueError("invalid Choir exposure")
        suppression = actor.get("choir_suppression")
        if suppression is not None and (
            not isinstance(suppression, dict)
            or set(suppression) != {"expires_round", "active"}
            or type(suppression["expires_round"]) is not int
            or suppression["expires_round"] < 1
            or type(suppression["active"]) is not bool
            or suppression["active"] != (round_number < suppression["expires_round"])
        ):
            raise ValueError("invalid Choir suppression")
        receipt = actor.get("choir_movement_round")
        if receipt is not None and (type(receipt) is not int or not 1 <= receipt <= round_number):
            raise ValueError("invalid Melody movement receipt")
        for condition in actor.get("conditions", []):
            if "choir_melody" in condition and (
                condition["choir_melody"] is not True
                or condition["type"] != "charmed"
                or not has_condition([condition], "charmed")
            ):
                raise ValueError("invalid Melody condition")
    return deepcopy(effects)
