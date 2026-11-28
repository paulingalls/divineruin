from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Literal

from inventory_pools import InventoryPool
from merchant_purse import MerchantState

PurchaseRefusal = Literal["not_sold_here", "out_of_stock", "insufficient_funds"]


@dataclass(frozen=True)
class PurchaseQuote:
    total_price_sp: int
    stock_count: int | None


def purchase_price(base_sp: int, quantity: int, disposition: str, traits: tuple[str, ...], *, pricing: dict) -> int:
    if type(base_sp) is not int or not 1 <= base_sp <= 2**53 - 1:
        raise ValueError("Purchase value_base must be a positive safe integer")
    if type(quantity) is not int or quantity < 1:
        raise ValueError("Purchase quantity must be a positive integer")
    multiplier = Fraction(str(pricing["purchase_disposition_multipliers"][disposition]))
    if "frontier" in traits:
        multiplier *= Fraction(str(pricing["purchase_frontier_multiplier"]))
    multiplier = min(Fraction(3), max(Fraction(1, 2), multiplier))
    return int(base_sp * quantity * multiplier + Fraction(1, 2))


def attempt_purchase(
    merchant: MerchantState,
    pool: InventoryPool,
    item: dict,
    quantity: int,
    disposition: str,
    traits: tuple[str, ...],
    *,
    balance_sp: Decimal,
    pricing: dict,
) -> PurchaseQuote | PurchaseRefusal:
    item_id = item["id"]
    unlimited = item_id in pool["tier_1_items"]
    finite = any(entry["item_id"] == item_id for entry in (*pool["tier_2_items"], *pool["tier_3_items"]))
    if not (unlimited or finite):
        return "not_sold_here"
    stock_count = None if unlimited else merchant["current_inventory"].get(item_id, 0)
    if stock_count is not None and stock_count < quantity:
        return "out_of_stock"
    price = purchase_price(item["value_base"], quantity, disposition, traits, pricing=pricing)
    if balance_sp < price:
        return "insufficient_funds"
    return PurchaseQuote(price, stock_count)
