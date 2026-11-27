"""Validate merchant buying rules and quote a deterministic unit sale price."""

import json
from typing import Literal, TypedDict

import asyncpg

import db
from catalog_parse import parse_dict, parse_int, parse_str, parse_str_list
from pricing_queries import SALE_DISPOSITIONS
from workspace import whole_silver


class InventoryPoolStock(TypedDict):
    item_id: str
    quantity: int
    price: int


class InventoryPool(TypedDict):
    id: str
    name: str
    location: str
    type: str
    restock_interval_hours: int
    items: list[InventoryPoolStock]
    buys: Literal["all"] | list[str]
    buys_rarities: list[str]


class SaleQuote(TypedDict):
    available: bool
    price_sp: int
    reason: str
    merchant_kind: str | None


def _buying_list(raw: object, vocabulary: set[str], ctx: str) -> list[str]:
    values = parse_str_list(raw, ctx)
    if not values:
        raise ValueError(f"{ctx} must not be empty")
    for value in values:
        if value not in vocabulary:
            raise ValueError(f"{ctx} contains unknown value {value!r}")
    return values


def _parse_stock(raw: object, ctx: str) -> list[InventoryPoolStock]:
    if not isinstance(raw, list):
        raise ValueError(f"{ctx} is not a list")
    items: list[InventoryPoolStock] = []
    for i, stock in enumerate(raw):
        entry = f"{ctx}[{i}]"
        data = parse_dict(stock, entry)
        items.append(
            InventoryPoolStock(
                item_id=parse_str(data.get("item_id"), f"{entry}.item_id"),
                quantity=parse_int(data.get("quantity"), f"{entry}.quantity"),
                price=parse_int(data.get("price"), f"{entry}.price"),
            )
        )
    return items


def parse_inventory_pools(rows: list[dict], item_rows: list[dict]) -> dict[str, InventoryPool]:
    if not item_rows:
        raise ValueError("items produced no rows")
    if not rows:
        raise ValueError("inventory_pools produced no rows")
    types: set[str] = set()
    rarities: set[str] = set()
    for row in item_rows:
        ctx = f"items[{row['id']}]"
        data = parse_dict(row["data"], ctx)
        types.add(parse_str(data.get("type"), f"{ctx}.type"))
        rarities.add(parse_str(data.get("rarity"), f"{ctx}.rarity"))

    pools: dict[str, InventoryPool] = {}
    for row in rows:
        pool_id = row["id"]
        ctx = f"inventory_pools[{pool_id}]"
        data = parse_dict(row["data"], ctx)
        raw_buys = data.get("buys")
        buys: Literal["all"] | list[str] = "all" if raw_buys == "all" else _buying_list(raw_buys, types, f"{ctx}.buys")
        pools[pool_id] = InventoryPool(
            id=pool_id,
            name=parse_str(data.get("name"), f"{ctx}.name"),
            location=parse_str(data.get("location"), f"{ctx}.location"),
            type=parse_str(data.get("type"), f"{ctx}.type"),
            restock_interval_hours=parse_int(data.get("restock_interval_hours"), f"{ctx}.restock_interval_hours"),
            items=_parse_stock(data.get("items"), f"{ctx}.items"),
            buys=buys,
            buys_rarities=_buying_list(data.get("buys_rarities"), rarities, f"{ctx}.buys_rarities"),
        )
    return pools


def validate_npc_pool_bindings(rows: list[dict], pools: dict[str, InventoryPool]) -> None:
    for row in rows:
        ctx = f"npcs[{row['id']}].inventory_pool"
        data = parse_dict(row["data"], f"npcs[{row['id']}]")
        if "inventory_pool" not in data:
            raise ValueError(f"{ctx} is required")
        pool_id = data["inventory_pool"]
        if pool_id is None:
            continue
        pool_id = parse_str(pool_id, ctx)
        if not pool_id.strip() or pool_id not in pools:
            raise ValueError(f"{ctx} references unknown pool {pool_id!r}")


async def get_inventory_pools(
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> dict[str, InventoryPool]:
    reader = conn if conn is not None else await db.get_pool()
    pools = await reader.fetch("SELECT id, data FROM inventory_pools ORDER BY id")
    items = await reader.fetch("SELECT id, data FROM items ORDER BY id")
    return parse_inventory_pools(
        [{"id": row["id"], "data": json.loads(row["data"])} for row in pools],
        [{"id": row["id"], "data": json.loads(row["data"])} for row in items],
    )


def _buys_type(pool: InventoryPool, item_type: str) -> bool:
    return pool["buys"] == "all" or item_type in pool["buys"]


def _buyer_kind(pools: dict[str, InventoryPool], item_type: str, rarity: str) -> str | None:
    buyers = [pool for pool in pools.values() if _buys_type(pool, item_type) and rarity in pool["buys_rarities"]]
    explicit = next((pool for pool in buyers if pool["buys"] != "all"), None)
    if explicit is not None:
        return explicit["type"]
    return buyers[0]["type"] if buyers else None


def _refuse(reason: str, merchant_kind: str | None = None) -> SaleQuote:
    return SaleQuote(available=False, price_sp=0, reason=reason, merchant_kind=merchant_kind)


def quote_sale(
    item: dict,
    pricing: dict,
    *,
    kind: str,
    disposition: str = "neutral",
    pool: InventoryPool | None = None,
    pools: dict[str, InventoryPool] | None = None,
) -> SaleQuote:
    """Quote a single item. Merchant inputs come from the validated pool catalog."""
    if disposition != "hostile" and disposition not in SALE_DISPOSITIONS:
        raise ValueError(f"unknown sale disposition {disposition!r}")
    merchant = None
    if kind == "merchant":
        if pool is None or pools is None:
            raise ValueError("merchant sale requires a pool and its catalog")
        if disposition == "hostile":
            return _refuse("hostile")
        merchant = (pool, pools)
        multiplier = float(pricing["sale_rate"]) * float(pricing["sale_disposition_multipliers"][disposition])
    elif kind == "crafted":
        multiplier = float(pricing["crafted_sale_rate"])
    else:
        raise ValueError(f"unknown sale kind {kind!r}")

    item_type = item["type"]
    if item_type == "quest_item" or item.get("quest_only") is True:
        return _refuse("quest_item")
    base = item.get("value_base")
    if base is None:
        return _refuse("no_value_base")
    if type(base) is not int or not 0 <= base <= 2**53 - 1:
        raise ValueError("value_base must be a non-negative safe integer")

    if merchant is not None:
        pool, pools = merchant
        rarity = item["rarity"]
        if not _buys_type(pool, item_type):
            return _refuse("wrong_type", _buyer_kind(pools, item_type, rarity))
        if rarity not in pool["buys_rarities"]:
            return _refuse("wrong_rarity", _buyer_kind(pools, item_type, rarity))

    # Scale the multiplier from the same JSON number representation as TypeScript.
    price = whole_silver(base, multiplier)
    if price == 0:
        return _refuse("priced_to_zero")
    return SaleQuote(available=True, price_sp=price, reason="", merchant_kind=None)
