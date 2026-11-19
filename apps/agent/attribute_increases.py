"""Deterministic attribute grants, saved offers and derived character maxima."""

from copy import deepcopy

from creation_classes import CLASSES
from creation_rules import CATEGORY_ATTRIBUTE_ORDER, calculate_ac
from hp_scaling import calculate_max_hp
from patron_passives import warriors_endurance
from rules_engine import ATTRIBUTE_INCREASE_LEVELS, attribute_modifier, calculate_max_pools

PREFIX = "attribute_increase_"
ATTRIBUTES = frozenset(CATEGORY_ATTRIBUTE_ORDER["martial"])


def records(player: dict) -> dict:
    saved = deepcopy(player.get("attribute_increases", {}))
    if not isinstance(saved, dict):
        raise ValueError("Malformed attribute increase records")
    for key, record in saved.items():
        if key not in {str(level) for level in ATTRIBUTE_INCREASE_LEVELS} or not isinstance(record, dict):
            raise ValueError("Malformed attribute increase record")
        deltas = record["allocation"]
        if (
            type(record["locked"]) is not bool
            or not isinstance(deltas, dict)
            or not deltas
            or any(k not in ATTRIBUTES or type(v) is not int or v <= 0 for k, v in deltas.items())
            or sum(deltas.values()) != 2
        ):
            raise ValueError("Malformed attribute increase allocation")
    return saved


def validate_scores(scores: dict) -> None:
    if set(scores) != ATTRIBUTES or any(type(v) is not int or not 1 <= v <= 20 for v in scores.values()):
        raise ValueError("Attribute scores must contain six integers from 1 to 20")


def recompute(player: dict) -> dict:
    scores = player["attributes"]
    validate_scores(scores)
    modifiers = {k: attribute_modifier(v) for k, v in scores.items()}
    maximum = calculate_max_hp(player["class"], player["level"], modifiers["constitution"])
    patch = {
        "attributes": dict(scores),
        "hp": {
            **player["hp"],
            "max": maximum,
            # Same ceiling as a rest: Warrior's Endurance is projected, never stored, but it still holds HP.
            "current": min(
                player["hp"]["current"],
                max(1, maximum + player.get("maxhp_override", 0) + warriors_endurance(player)),
            ),
        },
        "ac": calculate_ac(player.get("equipment", {}), scores["dexterity"]),
    }
    pools = calculate_max_pools(player["class"], player["level"], modifiers)
    for name in ("stamina", "focus"):
        maximum = getattr(pools, name)
        if name in player and maximum is not None:
            patch[name] = {**player[name], "max": maximum, "current": min(player[name]["current"], maximum)}
    return patch


def receipt(player_id: str, player: dict, level: str, record: dict) -> dict:
    base = dict(player["attributes"])
    for key, delta in record["allocation"].items():
        base[key] -= delta
    return {
        "player_id": player_id,
        "level": int(level),
        "choice_id": PREFIX + level,
        "allocation": dict(record["allocation"]),
        "scores": dict(player["attributes"]),
        "options": [key for key in sorted(ATTRIBUTES) if base[key] <= 18],
        "resolve_with": "select",
        "redirect_available": not record["locked"],
        "redirect_until": "next_long_rest",
        "narration_cue": "Speak the new attribute scores. The player can redirect these two points with select until their next long rest.",
    }


def offers(player_id: str, player: dict) -> list[dict]:
    return [
        receipt(player_id, player, level, record) for level, record in records(player).items() if not record["locked"]
    ]


def advance(player_id: str, player: dict, new_level: int) -> tuple[dict, list[dict], list[dict]]:
    working = deepcopy(player)
    saved = records(player)
    increases, hp_gains = [], []
    validate_scores(working["attributes"])
    order = CATEGORY_ATTRIBUTE_ORDER[CLASSES[player["class"]].category]
    for level in range(player.get("level", 1) + 1, new_level + 1):
        before_hp = calculate_max_hp(
            player["class"], level - 1, attribute_modifier(working["attributes"]["constitution"])
        )
        if level in ATTRIBUTE_INCREASE_LEVELS:
            if str(level) in saved:
                raise ValueError(f"Attribute increase for level {level} is already recorded")
            allocation = {}
            for _ in range(2):
                target = next((key for key in order if working["attributes"][key] < 20), None)
                if target is None:
                    raise ValueError("No attribute has capacity for the increase")
                working["attributes"][target] += 1
                allocation[target] = allocation.get(target, 0) + 1
            saved[str(level)] = {"allocation": allocation, "locked": False}
            increases.append(receipt(player_id, working, str(level), saved[str(level)]))
        working["level"] = level
        after_hp = calculate_max_hp(player["class"], level, attribute_modifier(working["attributes"]["constitution"]))
        hp_gains.append({"level": level, "hp_gain": after_hp - before_hp})
    return {**recompute(working), "attribute_increases": saved}, increases, hp_gains
