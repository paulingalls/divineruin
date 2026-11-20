"""Project owned catalog gear into the existing character equipment slots."""

from livekit.agents import ToolError

from archetypes import get_archetype_chassis

SLOTS = {"weapon": "main_hand", "armor": "armor", "shield": "shield"}
ARMOR_WEIGHTS = {"light", "medium", "heavy"}


def loadout_entry(item_id: str, item: dict, archetype: str) -> tuple[str, dict]:
    kind = item["type"]
    tags = set(item["tags"])
    slot = SLOTS.get(kind)
    if slot is None or "cloak" in tags:
        raise ToolError(f"{item['name']} cannot be equipped in a weapon, armor or shield slot.")
    entry = {"id": item_id, "name": item["name"]}
    if kind == "weapon":
        effect = next(effect for effect in item["effects"] if effect["type"] == "weapon")
        entry.update(damage=item["damage_dice"], damage_type=effect["damage_type"], properties=item["properties"])
        # The catalog tags a thrown melee weapon "ranged" too; only a weapon with no melee use attacks at range.
        if item.get("subtype") == "ranged" or ("ranged" in tags and "melee" not in tags):
            entry["ranged"] = True
    else:
        weight = "shield"
        if kind == "armor":
            weights = ARMOR_WEIGHTS.intersection(tags | {item.get("subtype")} | set(item["armor_properties"]))
            if len(weights) != 1:
                raise ToolError(f"{item['name']} must name exactly one armor weight class.")
            (weight,) = weights
            entry["weight_class"] = weight
        proficiencies = get_archetype_chassis(archetype).armor_proficiencies
        if weight not in proficiencies and not (f"{weight}_nonmetal" in proficiencies and "metal" not in tags):
            raise ToolError(f"You lack {weight} proficiency for {item['name']}.")
        entry["ac_bonus"] = item["ac"]
    return slot, entry
