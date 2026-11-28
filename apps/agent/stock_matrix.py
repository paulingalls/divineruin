"""Compute the settlement policy for limited and unique merchant stock."""

from collections.abc import Sequence
from fractions import Fraction

from inventory_pools import InventoryPoolTier2, InventoryPoolTier3
from sale_pricing import economy_size, economy_traits


def _stock_size(size: str) -> str:
    size = economy_size(size, "stock")
    return "city" if size == "keldaran_hold" else size


def stock_range(entry: InventoryPoolTier2, size: str) -> list[int]:
    size = _stock_size(size)
    return entry["quantity_by_settlement"]["city" if size == "capital" else size]


def _modifiers(traits: Sequence[str], pricing: dict) -> list[dict]:
    return [pricing["stock_modifiers"][trait] for trait in economy_traits(traits, "stock")]


def stock_quantity(
    entry: InventoryPoolTier2, size: str, traits: Sequence[str], rolled: int, *, pool_id: str, pricing: dict
) -> int:
    low, high = stock_range(entry, size)
    if type(rolled) is not int or not low <= rolled <= high:
        raise ValueError(f"rolled must be an integer in [{low}, {high}]: {rolled!r}")
    # The authored city range already includes the city size multiplier.
    scale = Fraction(4, 3) if size == "capital" else Fraction(1)
    for modifier in _modifiers(traits, pricing):
        factor = modifier["quantity_multiplier"]
        if isinstance(factor, dict):
            if pool_id not in factor:
                raise ValueError(f"Military stock quantity_multiplier has no pool {pool_id!r}")
            factor = factor[pool_id]
        scale *= Fraction(str(factor))
    return int(rolled * scale + Fraction(1, 2))


def _has_tier_3(size: str, modifiers: list[dict]) -> bool:
    return size not in ("hamlet", "village") and all(row["tier_3_allowed"] for row in modifiers)


def tier_3_chance(entry: InventoryPoolTier3, size: str, traits: Sequence[str], *, pricing: dict) -> float:
    size = _stock_size(size)
    modifiers = _modifiers(traits, pricing)
    if not _has_tier_3(size, modifiers) or size not in entry["settlements"]:
        return 0
    return min(1.0, entry["presence_chance"] + sum(row["tier_3_chance_bonus"] for row in modifiers))


def tier_3_limit(size: str, traits: Sequence[str], eligible_count: int, *, pricing: dict) -> int:
    size = _stock_size(size)
    if not _has_tier_3(size, _modifiers(traits, pricing)):
        return 0
    return min(2, eligible_count) if size == "town" else eligible_count
