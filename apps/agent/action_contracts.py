"""Catalog executable extensions shared with the combat load boundary."""

import re
from typing import Never

import conditions

EXECUTABLE_KINDS = ("attack", "healing", "prepare_attack", "charm", "silence", "spell_redirect")
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
    validate_durability_rider(action, path)
    validate_resolution(action, path)
    if kind not in ("charm", "silence", "spell_redirect") and any(key in action for key in CHOIR_EFFECT_FIELDS):
        invalid(f"{path}.kind")
    if kind in ("charm", "silence", "spell_redirect"):
        validate_choir_effect(action, path)
        return
    if "attack_source" in action:
        if kind != "attack" or action["attack_source"] != "catalog":
            invalid(f"{path}.attack_source")
        save_only = (
            action.get("resolution") == "save"
            or action.get("half_on_success") is True
            or action.get("damage") in ("0", 0)
        )
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


STRUCTURED_FIELDS = ("resolution", "save_success_damage", "conditions_on_failure", "conditions_on_success")


def validate_resolution(action, path):
    if not any(key in action for key in STRUCTURED_FIELDS):
        return
    mode = action.get("resolution")
    if action.get("kind", "attack") != "attack" or mode not in ("save", "hit_then_save"):
        invalid(f"{path}.resolution")
    if any(key in action for key in ("applies_condition", "duration", "half_on_success", "escape_dc")):
        invalid(f"{path}.resolution")
    if not isinstance(action.get("save"), str) or action["save"].lower() not in (
        "str",
        "dex",
        "con",
        "int",
        "wis",
        "cha",
        "strength",
        "dexterity",
        "constitution",
        "intelligence",
        "wisdom",
        "charisma",
    ):
        invalid(f"{path}.save")
    if not positive_integer(action.get("dc")):
        invalid(f"{path}.dc")
    if not isinstance(action.get("damage"), str) or not re.fullmatch(
        r"[1-9][0-9]*d[1-9][0-9]*(?:[+-][0-9]+)?", action["damage"]
    ):
        invalid(f"{path}.damage")
    if not isinstance(action.get("damage_type"), str) or not action["damage_type"]:
        invalid(f"{path}.damage_type")
    if not positive_integer(action.get("reach")) or action.get("type") not in ("area", "ranged", "melee"):
        invalid(f"{path}.reach")
    if mode == "save":
        if action.get("save_success_damage") not in ("none", "half"):
            invalid(f"{path}.save_success_damage")
        if "to_hit" in action and (type(action["to_hit"]) is not int or action["to_hit"] != 0):
            invalid(f"{path}.to_hit")
    elif "save_success_damage" in action or type(action.get("to_hit")) is not int:
        invalid(f"{path}.to_hit")
    for key in ("conditions_on_failure", "conditions_on_success"):
        riders = action.get(key)
        if not isinstance(riders, list):
            invalid(f"{path}.{key}")
        seen = set()
        for rider in riders:
            if not isinstance(rider, dict) or set(rider) != {"applies_condition", "duration"}:
                invalid(f"{path}.{key}")
            condition = rider["applies_condition"]
            if not isinstance(condition, str) or condition not in conditions.CONDITION_CATALOG or condition in seen:
                invalid(f"{path}.{key}.applies_condition")
            seen.add(condition)
            if not positive_integer(rider["duration"]):
                invalid(f"{path}.{key}.duration")


CHOIR_EFFECT_FIELDS = ("duration_dice", "movement", "radius_ft", "rounds", "trigger", "redirect")


def validate_choir_effect(action, path):
    kind = action["kind"]
    if any(key in action for key in (*STRIKE_FIELDS, *EFFECT_FIELDS, *STRUCTURED_FIELDS, "duration", "to_hit")):
        allowed = ("save", "dc") if kind != "silence" else ()
        for key in (*STRIKE_FIELDS, *EFFECT_FIELDS, *STRUCTURED_FIELDS, "duration", "to_hit"):
            if key in action and key not in allowed:
                invalid(f"{path}.{key}")
    fields = {
        "charm": ("duration_dice", "movement"),
        "silence": ("radius_ft", "rounds"),
        "spell_redirect": ("trigger", "redirect"),
    }[kind]
    for key in CHOIR_EFFECT_FIELDS:
        if key in action and key not in fields:
            invalid(f"{path}.{key}")
    if kind in ("charm", "spell_redirect"):
        if not isinstance(action.get("save"), str) or action["save"].lower() not in ("wis", "wisdom"):
            invalid(f"{path}.save")
        if not positive_integer(action.get("dc")):
            invalid(f"{path}.dc")
    if kind == "charm":
        if action.get("duration_dice") != "1d4" or action.get("movement") != "approach_source":
            invalid(f"{path}.duration_dice")
    elif kind == "silence":
        if not positive_integer(action.get("radius_ft")) or not positive_integer(action.get("rounds")):
            invalid(f"{path}.radius_ft")
    elif action.get("trigger") != "verbal_spell" or action.get("redirect") != "caster":
        invalid(f"{path}.trigger")
    if kind == "spell_redirect" and action.get("recharge") is not None:
        invalid(f"{path}.recharge")
    if "recharge" in action and not (kind == "spell_redirect" and action["recharge"] is None):
        validate_recharge(action["recharge"], f"{path}.recharge")


def validate_durability_rider(action, path):
    if "durability_rider" not in action:
        return
    rider = action["durability_rider"]
    path = f"{path}.durability_rider"
    if action.get("kind", "attack") != "attack" or action.get("resolution") == "save" or action.get("half_on_success"):
        invalid(path)
    if not isinstance(rider, dict) or set(rider) != {"save", "dc", "dice", "target"}:
        invalid(path)
    if rider["save"] not in ("STR", "DEX", "CON", "INT", "WIS", "CHA"):
        invalid(f"{path}.save")
    if not positive_integer(rider["dc"]):
        invalid(f"{path}.dc")
    if not isinstance(rider["dice"], str) or not re.fullmatch(r"[1-9][0-9]*d[1-9][0-9]*", rider["dice"]):
        invalid(f"{path}.dice")
    if rider["target"] != "selected_player_held_item":
        invalid(f"{path}.target")
