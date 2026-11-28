"""Validate merchant buying rules and quote a deterministic unit sale price."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypedDict, cast

from catalog_parse import parse_dict
from inventory_pools import InventoryPool
from workspace import SettlementSize, whole_silver

SALE_DISPOSITIONS = ("unfriendly", "neutral", "friendly", "trusted")


ECONOMY_SIZES = (*tuple(SettlementSize), "capital")
ECONOMY_TRAITS = (
    "prosperous",
    "struggling",
    "military",
    "scholarly",
    "corrupt",
    "devout",
    "frontier",
    "refuge",
    "trade_hub",
)


def economy_size(raw: object, ctx: str) -> str:
    if raw not in ECONOMY_SIZES:
        raise ValueError(f"{ctx}.settlement_tier is unknown: {raw!r}")
    return cast(str, raw)


def economy_traits(raw: object, ctx: str) -> tuple[str, ...]:
    traits = tuple(raw) if isinstance(raw, Sequence) and not isinstance(raw, str) else (raw,)
    if not traits:
        raise ValueError(f"{ctx}.personality must contain a trait")
    for trait in traits:
        if trait not in ECONOMY_TRAITS:
            raise ValueError(f"{ctx}.personality is unknown: {trait!r}")
    return cast(tuple[str, ...], traits)


def merchant_gold_allocation(pool: InventoryPool, location: dict | None, pricing: dict, *, location_id: str) -> int:
    ctx = f"locations[{location_id}]"
    data = parse_dict(location, ctx)
    tier = economy_size(data.get("settlement_tier"), ctx)
    traits = economy_traits(data.get("personality"), ctx)
    kind = pool["merchant_kind"]
    base = pricing["merchant_gold_sp"][tier][kind]
    if base is None:
        raise ValueError(f"merchant_gold_sp.{tier}.{kind} is unavailable")
    buys = pool["buys"]
    military_kind = "arms" if buys != "all" and ("weapon" in buys or "armor" in buys) else "other"
    multipliers = pricing["merchant_gold_personality_multipliers"]
    return whole_silver(
        int(base),
        *(multipliers[trait][military_kind] if trait == "military" else multipliers[trait] for trait in traits),
    )


class SaleQuote(TypedDict):
    available: bool
    price_sp: int
    reason: str
    merchant_kind: str | None


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
    """Quote a single item. Merchant suggestions come from NPC-bound pools."""
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
