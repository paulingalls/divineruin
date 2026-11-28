"""Roll finite merchant stock for an Aethos dawn."""

from collections.abc import Mapping, Sequence
from random import Random

from inventory_pools import InventoryPool, InventoryPoolTier3
from stock_matrix import stock_quantity, stock_range, tier_3_chance, tier_3_limit


def daily_restock_at_dawn(
    pool: InventoryPool,
    size: str,
    traits: Sequence[str],
    npc_id: str,
    day: int,
    previous: tuple[int, Mapping[str, int]] | None,
    *,
    pricing: dict,
) -> dict[str, int]:
    """Roll daily stock and carry this week's remaining weekly stock."""
    week = day // 7
    daily_rng = Random(f"{npc_id}:day:{day}")
    weekly_rng = Random(f"{npc_id}:week:{week}")
    carried = previous[1] if previous is not None and previous[0] // 7 == week else None
    inventory = {}
    for entry in pool["tier_2_items"]:
        rolled = daily_rng.randint(*stock_range(entry, size))
        count = stock_quantity(entry, size, traits, rolled, pool_id=pool["id"], pricing=pricing)
        if count:
            inventory[entry["item_id"]] = count

    groups: dict[str, list[InventoryPoolTier3]] = {}
    weekly: dict[str, int] = {}
    daily: dict[str, int] = {}
    for entry in pool["tier_3_items"]:
        item_id = entry["item_id"]
        chance = tier_3_chance(entry, size, traits, pricing=pricing)
        if entry["restock_check"] == "daily":
            if daily_rng.random() < chance:
                daily[item_id] = _quantity(entry, daily_rng)
        elif "rotation_group" in entry:
            if chance > 0:
                groups.setdefault(entry["rotation_group"], []).append(entry)
        elif carried is not None:
            if chance > 0 and (count := carried.get(item_id, 0)):
                weekly[item_id] = count
        elif weekly_rng.random() < chance:
            weekly[item_id] = _quantity(entry, weekly_rng)

    rotating = {}
    for members in groups.values():
        if carried is None:
            chosen = weekly_rng.choice(members)
            rotating[chosen["item_id"]] = _quantity(chosen, weekly_rng)
        else:
            for entry in members:
                item_id = entry["item_id"]
                if count := carried.get(item_id, 0):
                    rotating[item_id] = count

    # Reserve slots for weekly stock before filling the shelf with daily rolls.
    candidates = rotating | weekly | daily
    limit = tier_3_limit(size, traits, len(candidates), pricing=pricing)
    inventory.update(list(candidates.items())[:limit])
    return inventory


def _quantity(entry: InventoryPoolTier3, rng: Random) -> int:
    return rng.randint(*entry["quantity"]) if "quantity" in entry else 1
