"""Infuse Item eligibility, player persistence, and tool receipts."""

import json

import asyncpg
from livekit.agents.llm import ToolError

import db_content_queries
from equipment_rules import weapon_effect, weapon_item_id

ABILITY_ID = "artificer_infuse_item"
EXPIRY = "next_long_rest"


def infusion_rules(level: int) -> tuple[int, int]:
    return (2, 3) if level >= 10 else (1, 1)


def records(player: dict) -> dict[str, dict[str, int]]:
    return player.get("weapon_infusions", {})


async def prepare(player: dict, *, conn: asyncpg.Connection) -> tuple[dict, dict]:
    weapon = player.get("equipment", {}).get("main_hand")
    if not weapon:
        raise ToolError("Equip a main-hand weapon before using Infuse Item.")
    item_id = weapon_item_id(weapon)
    item = await db_content_queries.get_item(item_id, conn=conn)
    if item is None or item["type"] != "weapon":
        raise ValueError(f"Main-hand equipment references invalid weapon {item_id!r}")
    if weapon_effect(item).get("magical", False):
        raise ToolError(f"{item['name']} is already magical and cannot be infused.")

    bonus, capacity = infusion_rules(player["level"])
    infusions = records(player).copy()
    order = max((record["order"] for record in infusions.values()), default=0) + 1
    infusions[item_id] = {"order": order}
    replaced = None
    while len(infusions) > capacity:
        replaced = min(infusions, key=lambda key: infusions[key]["order"])
        del infusions[replaced]
    return infusions, {
        "item_id": item_id,
        "name": item["name"],
        **effect_summary(bonus),
        "replaced_item_id": replaced,
    }


async def save(player_id: str, infusions: dict, *, conn: asyncpg.Connection) -> None:
    await conn.execute(
        "UPDATE players SET data=jsonb_set(data, '{weapon_infusions}', $2::jsonb) WHERE player_id=$1",
        player_id,
        json.dumps(infusions),
    )


async def clear(player_id: str, player: dict, *, conn: asyncpg.Connection) -> None:
    if "weapon_infusions" in player:
        await conn.execute("UPDATE players SET data=data-'weapon_infusions' WHERE player_id=$1", player_id)


def effect_summary(bonus: int) -> dict:
    return {"attack_bonus": bonus, "damage_bonus": bonus, "magical": True, "expiry": EXPIRY}


def describe(player: dict) -> dict:
    bonus, capacity = infusion_rules(player["level"])
    weapon = player.get("equipment", {}).get("main_hand")
    equipped_id = weapon_item_id(weapon) if weapon else None
    infusions = records(player)
    return {
        **effect_summary(bonus),
        "scope": "own_equipped_nonmagical_main_hand_weapon",
        "capacity": capacity,
        "active": [
            {"item_id": item_id, "bonus": bonus, "equipped": item_id == equipped_id}
            for item_id in sorted(infusions, key=lambda key: infusions[key]["order"])
        ],
    }
