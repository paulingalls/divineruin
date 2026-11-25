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
        effect = next(effect for effect in item["effects"] if effect["type"] == "weapon")
        entry.update({field: item[field] for field in PROFILE_FIELDS})
        entry.update(damage=item["damage_dice"], damage_type=effect["damage_type"], properties=item["properties"])
        weapon_proficient = has_weapon_proficiency(chassis.weapon_proficiencies, entry)
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


async def resolve_weapon_profile(attacker_type: str, action: dict, *, weapon_attack: bool, conn) -> dict | None:
    if not needs_weapon_profile(attacker_type, action, weapon_attack=weapon_attack):
        return None
    if PROFILE_FIELDS.keys() <= action.keys():
        return action

    # Older equipment and combat snapshots omit the catalog profile.
    name = action.get("name")
    item_id = action.get("id", STARTER_ITEM_IDS.get(name))
    if not isinstance(item_id, str) or not item_id:
        raise ValueError(f"Player weapon attack {name!r} has no catalog identity: {item_id!r}")
    item = await db_content_queries.get_item(item_id, conn=conn)
    if item is None or item.get("type") != "weapon":
        raise ValueError(f"Player weapon attack {name!r} references invalid weapon {item_id!r}")
    return item
