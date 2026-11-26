"""Project owned catalog gear into the existing character equipment slots."""

from livekit.agents import ToolError

import db_content_queries
from archetypes import get_archetype_chassis
from combat_enhancers import SHIELD_BASH_ACTION
from creation_classes import STARTER_ITEM_IDS
from weapon_proficiency import PROFILE_FIELDS, has_weapon_proficiency

SLOTS = {"weapon": "main_hand", "armor": "armor", "shield": "shield"}
ARMOR_WEIGHTS = {"light", "medium", "heavy"}


def loadout_entry(item_id: str, item: dict, archetype: str) -> tuple[str, dict, bool | None]:
    kind = item["type"]
    tags = set(item["tags"])
    slot = SLOTS.get(kind)
    if slot is None or "cloak" in tags:
        raise ToolError(f"{item['name']} cannot be equipped in a weapon, armor or shield slot.")
    entry = {"id": item_id, "name": item["name"]}
    chassis = get_archetype_chassis(archetype)
    weapon_proficient = None
    if kind == "weapon":
        effect = weapon_effect(item)
        entry.update(damage=item["damage_dice"], damage_type=effect["damage_type"], properties=item["properties"])
        weapon_proficient = has_weapon_proficiency(chassis.weapon_proficiencies, item)
        if item["weapon_range"] == "ranged":
            entry["ranged"] = True
    else:
        weight = "shield"
        if kind == "armor":
            weights = ARMOR_WEIGHTS.intersection(tags | {item.get("subtype")} | set(item["armor_properties"]))
            if len(weights) != 1:
                raise ToolError(f"{item['name']} must name exactly one armor weight class.")
            (weight,) = weights
            entry["weight_class"] = weight
        proficiencies = chassis.armor_proficiencies
        if weight not in proficiencies and not (f"{weight}_nonmetal" in proficiencies and "metal" not in tags):
            raise ToolError(f"You lack {weight} proficiency for {item['name']}.")
        entry["ac_bonus"] = item["ac"]
    return slot, entry, weapon_proficient


def needs_weapon_profile(attacker_type: str, action: dict, *, weapon_attack: bool) -> bool:
    return (
        attacker_type == "player"
        and weapon_attack
        and not (action.get("name") == SHIELD_BASH_ACTION["name"] and "id" not in action)
    )


def weapon_item_id(weapon: dict) -> str:
    name = weapon.get("name")
    item_id = weapon.get("id", STARTER_ITEM_IDS.get(name))
    if not isinstance(item_id, str) or not item_id:
        raise ValueError(f"Player weapon {name!r} has no catalog identity: {item_id!r}")
    return item_id


def weapon_effect(item: dict) -> dict:
    return next(effect for effect in item["effects"] if effect["type"] == "weapon")


async def resolve_weapon_profile(
    attacker_type: str, action: dict, *, player: dict | None, weapon_attack: bool, conn
) -> dict | None:
    from infusion import records

    if not needs_weapon_profile(attacker_type, action, weapon_attack=weapon_attack):
        return None
    if "id" not in action and PROFILE_FIELDS.keys() <= action.keys():
        return action

    # Older equipment and combat snapshots omit the catalog profile.
    item_id = weapon_item_id(action)
    item = await db_content_queries.get_item(item_id, conn=conn)
    if item is None or item.get("type") != "weapon":
        raise ValueError(f"Player weapon attack {action.get('name')!r} references invalid weapon {item_id!r}")
    infusion = records(player).get(item_id) if player is not None else None
    if infusion is None:
        return item
    effect = weapon_effect(item)
    effects = [{**effect, "magical": True} if entry is effect else entry for entry in item["effects"]]
    return {**item, "effects": effects, "infusion_bonus": infusion["bonus"]}


def with_weapon_magic(action: dict, profile: dict | None) -> dict:
    if profile is None or profile is action:
        return action
    return {
        **action,
        "magical": weapon_effect(profile).get("magical", False),
        "infusion_bonus": profile.get("infusion_bonus", 0),
    }
