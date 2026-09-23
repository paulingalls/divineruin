"""Validation for the bestiary's universal creature stat block."""

import json
from pathlib import Path

from world_regions import REGION_IDS

CATEGORIES = ("hollow", "beast", "humanoid", "construct", "undead", "elemental")
ATTACK_TYPES = ("melee", "ranged", "area")
HOLLOW_CLASSES = ("drift", "rend", "wrack", "named")
ATTRIBUTES = ("STR", "DEX", "CON", "INT", "WIS", "CHA")
LOOT_CATALOG = Path(__file__).resolve().parents[2] / "content/loot_tables.json"


def validate_creature_stat_block(creature: object) -> list[str]:
    problems: list[str] = []
    if not isinstance(creature, dict):
        return ["creature: expected object"]

    def field(obj: dict, key: str, path: str, kind: str, nullable: bool = False):
        name = f"{path}.{key}" if path else key
        if key not in obj:
            problems.append(f"{name}: required")
            return None
        value = obj[key]
        if nullable and value is None:
            return value
        valid = {
            "string": lambda v: isinstance(v, str),
            "integer": lambda v: type(v) is int,
            "object": lambda v: isinstance(v, dict),
            "array": lambda v: isinstance(v, list),
        }[kind](value)
        if not valid:
            problems.append(f"{name}: expected {kind}")
            return None
        return value

    for key in ("id", "name"):
        field(creature, key, "", "string")
    category = field(creature, "category", "", "string")
    if isinstance(category, str) and category not in CATEGORIES:
        problems.append("category: expected " + "|".join(CATEGORIES))
    tier = field(creature, "tier", "", "integer")
    if type(tier) is int and tier not in (1, 2, 3, 4):
        problems.append("tier: expected integer 1-4")
    home_region = field(creature, "home_region", "", "string")
    if isinstance(home_region, str) and home_region not in (*REGION_IDS, "multi_region"):
        problems.append("home_region: unknown region")
    regions = field(creature, "regions", "", "array")
    if isinstance(regions, list):
        if not regions:
            problems.append("regions: expected non-empty array")
        for i, region in enumerate(regions):
            if region not in REGION_IDS:
                problems.append(f"regions[{i}]: unknown region")
    field(creature, "description", "", "string")
    for key in ("level", "hp", "ac", "speed"):
        field(creature, key, "", "integer")
    attributes = field(creature, "attributes", "", "object")
    if isinstance(attributes, dict):
        for key in ATTRIBUTES:
            field(attributes, key, "attributes", "integer")
    saves = field(creature, "save_proficiencies", "", "array")
    if isinstance(saves, list):
        for i, value in enumerate(saves):
            if not isinstance(value, str):
                problems.append(f"save_proficiencies[{i}]: expected string")
    attacks = field(creature, "attacks", "", "array")
    if isinstance(attacks, list):
        for i, attack in enumerate(attacks):
            path = f"attacks[{i}]"
            if not isinstance(attack, dict):
                problems.append(f"{path}: expected object")
                continue
            field(attack, "name", path, "string")
            kind = field(attack, "type", path, "string")
            if isinstance(kind, str) and kind not in ATTACK_TYPES:
                problems.append(f"{path}.type: expected melee|ranged|area")
            for key in ("reach", "to_hit"):
                field(attack, key, path, "integer")
            for key in ("damage", "damage_type"):
                field(attack, key, path, "string")
            field(attack, "special", path, "string", True)
            field(attack, "audio", path, "string")
    field(creature, "multiattack", "", "string", True)
    for group in ("passives", "actives", "reactions"):
        abilities = field(creature, group, "", "array")
        if isinstance(abilities, list):
            for i, ability in enumerate(abilities):
                path = f"{group}[{i}]"
                if not isinstance(ability, dict):
                    problems.append(f"{path}: expected object")
                    continue
                for key in ("name", "description", "narration_cue"):
                    field(ability, key, path, "string")
                for key in ("recharge", "audio"):
                    field(ability, key, path, "string", True)
    if "hollow" not in creature:
        problems.append("hollow: required")
    elif category == "hollow":
        hollow = creature["hollow"]
        if not isinstance(hollow, dict):
            problems.append("hollow: expected object")
        else:
            cls = field(hollow, "class", "hollow", "string")
            if isinstance(cls, str) and cls not in HOLLOW_CLASSES:
                problems.append("hollow.class: expected drift|rend|wrack|named")
            for key in ("corruption_aura", "resonance_on_death"):
                field(hollow, key, "hollow", "integer")
            field(hollow, "veil_effect", "hollow", "string")
            vulnerable = field(hollow, "vulnerable_to", "hollow", "array")
            if isinstance(vulnerable, list):
                for i, value in enumerate(vulnerable):
                    if not isinstance(value, str):
                        problems.append(f"hollow.vulnerable_to[{i}]: expected string")
    behavior = field(creature, "behavior", "", "object")
    if isinstance(behavior, dict):
        for key in ("tactics", "morale", "group_size"):
            field(behavior, key, "behavior", "string")
        environment = field(behavior, "environment", "behavior", "array")
        if isinstance(environment, list):
            for i, value in enumerate(environment):
                if not isinstance(value, str):
                    problems.append(f"behavior.environment[{i}]: expected string")
    narration = field(creature, "narration", "", "object")
    if isinstance(narration, dict):
        for key in ("first_sighting", "attack_cue", "wounded_cue", "death_cue", "ambient_cue"):
            field(narration, key, "narration", "string")
    audio = field(creature, "audio", "", "object")
    if isinstance(audio, dict):
        for key in ("ambient", "attack", "hit", "death"):
            field(audio, key, "audio", "string")
        special = field(audio, "special", "audio", "object")
        if isinstance(special, dict):
            for key, value in special.items():
                if not isinstance(value, str):
                    problems.append(f"audio.special.{key}: expected string")
    loot_id = field(creature, "loot_table_id", "", "string")
    if isinstance(loot_id, str):
        ids = {row["id"] for row in json.loads(LOOT_CATALOG.read_text())}
        if not ids:
            raise ValueError("loot catalog is empty")
        if loot_id not in ids:
            problems.append("loot_table_id: unknown loot table")
    field(creature, "xp_reward", "", "integer")
    return problems
