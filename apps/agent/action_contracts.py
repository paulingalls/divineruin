"""Catalog executable extensions shared with the combat load boundary."""

import re
from typing import Never

import conditions

EXECUTABLE_KINDS = ("attack", "healing", "prepare_attack")
STRIKE_FIELDS = ("damage", "damage_type", "applies_condition", "save", "dc", "half_on_success", "escape_dc")
EFFECT_FIELDS = ("target_group", "healing", "advantage", "on_hit")


def invalid(path: str) -> Never:
    raise ValueError(f"{path}: invalid")


def positive_integer(value: object) -> bool:
    return type(value) is int and value > 0


def validate_recharge(value: object, path: str) -> None:
    if not isinstance(value, dict):
        invalid(path)
    kind = value.get("kind")
    if kind not in ("roll", "encounter", "round"):
        invalid(f"{path}.kind")
    fields = ("kind", "die", "threshold") if kind == "roll" else ("kind", "uses")
    for key in value:
        if key not in fields:
            invalid(f"{path}.{key}")
    if kind == "roll":
        if type(value.get("die")) is not int or value["die"] != 6:
            invalid(f"{path}.die")
        if not positive_integer(value.get("threshold")) or value["threshold"] > 6:
            invalid(f"{path}.threshold")
    elif not positive_integer(value.get("uses")):
        invalid(f"{path}.uses")


def validate_action_extensions(action: dict, path: str) -> None:
    kind = action.get("kind", "attack")
    if "attack_source" in action:
        if kind != "attack" or action["attack_source"] != "catalog":
            invalid(f"{path}.attack_source")
        save_only = action.get("half_on_success") is True or action.get("damage") in ("0", 0)
        if not save_only and type(action.get("to_hit")) is not int:
            invalid(f"{path}.to_hit")
    if "self_heal" in action and (
        kind != "attack" or action["self_heal"] != "damage_dealt" or action.get("damage") in (None, "", "0", 0)
    ):
        invalid(f"{path}.self_heal")
    if kind in EXECUTABLE_KINDS and "recharge" in action:
        validate_recharge(action["recharge"], f"{path}.recharge")
    if "advantage" in action and type(action["advantage"]) is not bool:
        invalid(f"{path}.advantage")
    if "duration" in action and not positive_integer(action["duration"]):
        invalid(f"{path}.duration")
    if kind == "attack":
        if action.get("kind") == "attack":
            for key in ("damage", "damage_type"):
                if not isinstance(action.get(key), str):
                    invalid(f"{path}.{key}")
        if action.get("kind") == "attack":
            for key in ("applies_condition", "save", "dc", "half_on_success", "escape_dc"):
                if key not in action:
                    continue
                expected = bool if key == "half_on_success" else int if key in ("dc", "escape_dc") else str
                if type(action[key]) is not expected:
                    invalid(f"{path}.{key}")
        if action.get("kind") == "attack" and action.get("damage") == "0":
            if not isinstance(action.get("applies_condition"), str) or not action["applies_condition"]:
                invalid(f"{path}.applies_condition")
            if action.get("damage_type") != "none":
                invalid(f"{path}.damage_type")
        forbidden = ("target_group", "healing", "on_hit")
    elif kind in ("healing", "prepare_attack"):
        forbidden = STRIKE_FIELDS
        if kind == "healing":
            forbidden += ("advantage", "on_hit")
            if action.get("target_group") != "allied_bandits":
                invalid(f"{path}.target_group")
            healing = action.get("healing")
            if not isinstance(healing, str) or not re.fullmatch(r"[1-9][0-9]*d[1-9][0-9]*(?:\+[0-9]+)?", healing):
                invalid(f"{path}.healing")
        else:
            forbidden += ("target_group", "healing")
            if action.get("advantage") is not True:
                invalid(f"{path}.advantage")
            rider = action.get("on_hit")
            if not isinstance(rider, dict):
                invalid(f"{path}.on_hit")
            if (
                not isinstance(rider.get("applies_condition"), str)
                or rider["applies_condition"] not in conditions.CONDITION_CATALOG
            ):
                invalid(f"{path}.on_hit.applies_condition")
            if not positive_integer(rider.get("duration")):
                invalid(f"{path}.on_hit.duration")
            for key in rider:
                if key not in ("applies_condition", "duration"):
                    invalid(f"{path}.on_hit.{key}")
    else:
        forbidden = EFFECT_FIELDS
    for key in forbidden:
        if key in action:
            invalid(f"{path}.{key}")
