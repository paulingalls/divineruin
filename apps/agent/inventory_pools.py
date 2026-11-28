"""Tiered inventory pool catalog and merchant bindings."""

import json
from collections.abc import Collection
from typing import Literal, NotRequired, TypedDict, cast

import asyncpg

from catalog_parse import parse_dict, parse_str, parse_str_list

MERCHANT_KINDS = ("general", "specialist", "exotic", "black_market")
_SINK_CATEGORIES = (
    "maintenance",
    "subsistence",
    "combat",
    "progression",
    "crafting",
    "service",
    "lifestyle",
    "endgame",
)
_TIER_2_SETTLEMENTS = ("hamlet", "village", "town", "city")
_TIER_3_SETTLEMENTS = (*_TIER_2_SETTLEMENTS, "capital")


class InventoryPoolTier2(TypedDict):
    item_id: str
    quantity_by_settlement: dict[str, list[int]]


class InventoryPoolTier3(TypedDict):
    item_id: str
    settlements: list[str]
    presence_chance: int | float
    restock_check: str
    rotation_group: NotRequired[str]
    quantity: NotRequired[list[int]]


class InventoryPool(TypedDict):
    id: str
    name: str
    type: str
    merchant_kind: str
    sink_category: str
    buys: Literal["all"] | list[str]
    buys_rarities: list[str]
    tier_1_items: list[str]
    tier_2_items: list[InventoryPoolTier2]
    tier_3_items: list[InventoryPoolTier3]


def _closed_record(raw: object, fields: Collection[str], ctx: str) -> dict:
    data = parse_dict(raw, ctx)
    for key in data:
        if key not in fields:
            raise ValueError(f"{ctx}.{key} is not a supported field")
    return data


def _token(raw: object, vocabulary: Collection[str], ctx: str) -> str:
    value = parse_str(raw, ctx)
    if value not in vocabulary:
        raise ValueError(f"{ctx} contains unknown value {value!r}")
    return value


def _token_list(raw: object, vocabulary: Collection[str], ctx: str) -> list[str]:
    values = parse_str_list(raw, ctx)
    if not values:
        raise ValueError(f"{ctx} must not be empty")
    return [_token(value, vocabulary, ctx) for value in values]


def _quantity(raw: object, ctx: str, floor: int) -> list[int]:
    if not isinstance(raw, list) or len(raw) != 2:
        raise ValueError(f"{ctx} must be a two-integer range")
    minimum, maximum = raw
    if type(minimum) is not int or type(maximum) is not int:
        raise ValueError(f"{ctx} must be a two-integer range")
    if minimum < floor:
        raise ValueError(f"{ctx} must start at {floor} or higher")
    if minimum > maximum:
        raise ValueError(f"{ctx} minimum exceeds maximum")
    return [minimum, maximum]


def _rows(raw: object, ctx: str) -> list:
    if not isinstance(raw, list):
        raise ValueError(f"{ctx} is not a list")
    return raw


def _tier_2(raw: object, item_ids: set[str], ctx: str) -> list[InventoryPoolTier2]:
    entries: list[InventoryPoolTier2] = []
    for index, row in enumerate(_rows(raw, ctx)):
        entry = f"{ctx}[{index}]"
        data = _closed_record(row, InventoryPoolTier2.__annotations__, entry)
        quantities = f"{entry}.quantity_by_settlement"
        ranges = _closed_record(data.get("quantity_by_settlement"), _TIER_2_SETTLEMENTS, quantities)
        entries.append(
            InventoryPoolTier2(
                item_id=_token(data.get("item_id"), item_ids, f"{entry}.item_id"),
                quantity_by_settlement={
                    size: _quantity(ranges.get(size), f"{quantities}.{size}", 0) for size in _TIER_2_SETTLEMENTS
                },
            )
        )
    return entries


def _tier_3(raw: object, item_ids: set[str], ctx: str) -> list[InventoryPoolTier3]:
    entries: list[InventoryPoolTier3] = []
    for index, row in enumerate(_rows(raw, ctx)):
        entry = f"{ctx}[{index}]"
        data = _closed_record(row, InventoryPoolTier3.__annotations__, entry)
        chance_field = f"{entry}.presence_chance"
        raw_chance = data.get("presence_chance")
        if type(raw_chance) not in (int, float):
            raise ValueError(f"{chance_field} must be a number")
        chance = cast(int | float, raw_chance)
        if not 0 < chance <= 1:
            raise ValueError(f"{chance_field} must be in (0, 1]")
        stock = InventoryPoolTier3(
            item_id=_token(data.get("item_id"), item_ids, f"{entry}.item_id"),
            settlements=_token_list(data.get("settlements"), _TIER_3_SETTLEMENTS, f"{entry}.settlements"),
            presence_chance=chance,
            restock_check=_token(data.get("restock_check"), ("daily", "weekly"), f"{entry}.restock_check"),
        )
        if "rotation_group" in data:
            rotation = parse_str(data["rotation_group"], f"{entry}.rotation_group")
            if not rotation:
                raise ValueError(f"{entry}.rotation_group must not be empty")
            stock["rotation_group"] = rotation
        if "quantity" in data:
            stock["quantity"] = _quantity(data["quantity"], f"{entry}.quantity", 1)
        entries.append(stock)
    return entries


def _parse_pool(pool_id: str, raw: object, item_ids: set[str], types: set[str], rarities: set[str]) -> InventoryPool:
    ctx = f"inventory_pools[{pool_id}]"
    data = _closed_record(raw, InventoryPool.__annotations__, ctx)
    raw_buys = data.get("buys")
    first = f"{ctx}.tier_1_items"
    tier_1 = [_token(item, item_ids, f"{first}[{i}]") for i, item in enumerate(_rows(data.get("tier_1_items"), first))]
    tier_2 = _tier_2(data.get("tier_2_items"), item_ids, f"{ctx}.tier_2_items")
    tier_3 = _tier_3(data.get("tier_3_items"), item_ids, f"{ctx}.tier_3_items")
    seen: set[str] = set()
    for tier, ids in enumerate((tier_1, [row["item_id"] for row in tier_2], [row["item_id"] for row in tier_3]), 1):
        for index, item_id in enumerate(ids):
            if item_id in seen:
                entry = f"{ctx}.tier_{tier}_items[{index}]"
                field = entry if tier == 1 else f"{entry}.item_id"
                raise ValueError(f"{field} contains duplicate item {item_id!r}")
            seen.add(item_id)
    return InventoryPool(
        id=pool_id,
        name=parse_str(data.get("name"), f"{ctx}.name"),
        type=parse_str(data.get("type"), f"{ctx}.type"),
        merchant_kind=_token(data.get("merchant_kind"), MERCHANT_KINDS, f"{ctx}.merchant_kind"),
        sink_category=_token(data.get("sink_category"), _SINK_CATEGORIES, f"{ctx}.sink_category"),
        buys="all" if raw_buys == "all" else _token_list(raw_buys, types, f"{ctx}.buys"),
        buys_rarities=_token_list(data.get("buys_rarities"), rarities, f"{ctx}.buys_rarities"),
        tier_1_items=tier_1,
        tier_2_items=tier_2,
        tier_3_items=tier_3,
    )


def parse_inventory_pools(rows: list[dict], item_rows: list[dict]) -> dict[str, InventoryPool]:
    if not item_rows:
        raise ValueError("items produced no rows")
    if not rows:
        raise ValueError("inventory_pools produced no rows")
    item_ids: set[str] = set()
    types: set[str] = set()
    rarities: set[str] = set()
    for row in item_rows:
        ctx = f"items[{row['id']}]"
        data = parse_dict(row["data"], ctx)
        item_ids.add(row["id"])
        types.add(parse_str(data.get("type"), f"{ctx}.type"))
        rarities.add(parse_str(data.get("rarity"), f"{ctx}.rarity"))

    return {row["id"]: _parse_pool(row["id"], row["data"], item_ids, types, rarities) for row in rows}


def bound_inventory_pools(rows: list[dict], pools: dict[str, InventoryPool]) -> dict[str, InventoryPool]:
    bound: set[str] = set()
    for row in rows:
        ctx = f"npcs[{row['id']}].inventory_pool"
        data = parse_dict(row["data"], f"npcs[{row['id']}]")
        if "inventory_pool" not in data:
            raise ValueError(f"{ctx} is required")
        binding = data["inventory_pool"]
        if binding is not None:
            pool_id = parse_str(binding, ctx)
            if pool_id not in pools:
                raise ValueError(f"{ctx} references unknown pool {pool_id!r}")
            bound.add(pool_id)
    return {pool_id: pools[pool_id] for pool_id in sorted(bound)}


async def get_inventory_pools(*, conn: asyncpg.Connection) -> dict[str, InventoryPool]:
    pools = await conn.fetch("SELECT id, data FROM inventory_pools")
    items = await conn.fetch("SELECT id, data FROM items")
    npcs = await conn.fetch("SELECT id, data FROM npcs")
    catalog = parse_inventory_pools(
        [{"id": row["id"], "data": json.loads(row["data"])} for row in pools],
        [{"id": row["id"], "data": json.loads(row["data"])} for row in items],
    )
    return bound_inventory_pools([{"id": row["id"], "data": json.loads(row["data"])} for row in npcs], catalog)
