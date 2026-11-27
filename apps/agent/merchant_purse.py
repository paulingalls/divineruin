"""Decide what a merchant can pay from its locked, day-scoped purse."""

import hashlib
import json
from typing import TypedDict

from workspace import whole_silver


class MerchantState(TypedDict):
    current_gold_sp: int
    max_gold_sp: int
    last_restock_day: int
    buyback_history: dict[str, int]
    consigned_items: list[dict]


class SaleOption(TypedDict):
    kind: str
    quantity: int
    total_price_sp: int
    offer_id: str


def buyback_limit(item: dict) -> int:
    if item["rarity"] in ("rare", "legendary"):
        return 1
    if item["rarity"] == "uncommon":
        return 2
    return 3 if item["type"] in ("weapon", "armor", "shield") else 5


def sale_terms(
    merchant: MerchantState, item: dict, item_id: str, quantity: int, unit_sp: int, disposition: str
) -> tuple[list[tuple[str, int]], dict]:
    bought = merchant["buyback_history"].get(item_id, 0)
    limit = buyback_limit(item)
    full_remaining = max(0, limit - bought)
    if bought > limit:
        return [], {"reason": "I've bought all of those I can take until dawn."}
    if quantity > (full_remaining or 1):
        reason = (
            f"I can only buy {full_remaining} more at full price, then one at half price."
            if full_remaining
            else "I can only buy one more, at half price."
        )
        return [], {"reason": reason, "full_price_quantity": full_remaining, "discounted_quantity": 1}

    cash = merchant["current_gold_sp"]
    if cash == 0:
        return [], {"reason": "I'm out of coin until dawn."}
    total_sp = unit_sp * quantity
    if bought == limit:
        discount = whole_silver(unit_sp, 0.5)
        return [("discount" if cash >= discount else "discount_partial", min(cash, discount))], {}
    if cash >= total_sp:
        return [("full", total_sp)], {}
    options = [("partial", cash)]
    if disposition in ("friendly", "trusted"):
        options.append(("consignment", total_sp))
    return options, {}


def bind_sale_option(kind: str, total_sp: int, quantity: int, quote_state: tuple) -> SaleOption:
    encoded = json.dumps((kind, total_sp, quantity, quote_state), sort_keys=True, separators=(",", ":"))
    return SaleOption(
        kind=kind,
        quantity=quantity,
        total_price_sp=total_sp,
        offer_id=hashlib.sha256(encoded.encode()).hexdigest(),
    )
