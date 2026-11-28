import json
from pathlib import Path

import pytest

from economy_pricing import parse_economy_pricing
from inventory_pools import InventoryPoolTier2, InventoryPoolTier3
from stock_matrix import stock_quantity, tier_3_chance, tier_3_limit

PRICING = Path(__file__).parents[3] / "content/pricing.json"


@pytest.mark.parametrize(
    "path,value,diagnostic",
    [
        (("refuge",), None, "requires exactly"),
        (
            ("isolated",),
            {"quantity_multiplier": 1, "tier_3_allowed": True, "tier_3_chance_bonus": 0},
            "requires exactly",
        ),
        (("prosperous", "tier_3_allowed"), None, "requires exactly"),
        (("prosperous", "extra"), 1, "requires exactly"),
        (("military", "quantity_multiplier"), [1], "quantity_multiplier"),
        (("military", "quantity_multiplier"), {}, "quantity_multiplier"),
        (("prosperous", "quantity_multiplier"), 0, "quantity_multiplier"),
        (("military", "quantity_multiplier", "general_supplies"), 0, "quantity_multiplier"),
        (("prosperous", "tier_3_allowed"), 1, "tier_3_allowed"),
        (("prosperous", "tier_3_chance_bonus"), True, "tier_3_chance_bonus"),
        (("prosperous", "tier_3_chance_bonus"), "0.15", "tier_3_chance_bonus"),
        (("prosperous", "tier_3_chance_bonus"), -0.01, "tier_3_chance_bonus"),
        (("prosperous", "tier_3_chance_bonus"), 1.01, "tier_3_chance_bonus"),
        (("prosperous", "tier_3_chance_bonus"), float("inf"), "tier_3_chance_bonus"),
        (("prosperous", "tier_3_chance_bonus"), 0.12345, "tier_3_chance_bonus"),
    ],
)
def test_pricing_rejects_malformed_stock_modifier(path, value, diagnostic):
    pricing = json.loads(PRICING.read_text())[0]
    target = pricing["stock_modifiers"]
    *parents, field = path
    for key in parents:
        target = target[key]
    if value is None:
        del target[field]
    else:
        target[field] = value
    with pytest.raises(ValueError, match=rf"economy.*stock_modifiers.*{diagnostic}"):
        parse_economy_pricing(pricing)


@pytest.fixture(scope="module")
def pricing() -> dict:
    return parse_economy_pricing(json.loads(PRICING.read_text())[0])


ENTRY = InventoryPoolTier2(item_id="spear_common", quantity_by_settlement={"hamlet": [0, 3], "city": [0, 3]})
UNIQUE = InventoryPoolTier3(item_id="spear_common", settlements=["city"], presence_chance=0.25, restock_check="daily")


@pytest.mark.parametrize("rolled", [-1, 4, 1.5, 1.0, True])
def test_stock_rejects_invalid_roll(rolled, pricing):
    with pytest.raises(ValueError, match="rolled"):
        stock_quantity(ENTRY, "city", ["scholarly"], rolled, pool_id="general_supplies", pricing=pricing)


@pytest.mark.parametrize(
    "size,traits,diagnostic",
    [
        ("metropolis", ["scholarly"], "metropolis"),
        ("city", ["scholarly", "isolated"], "isolated"),
        ("hamlet", ["struggling", "cursed"], "cursed"),
        ("city", [], "personality"),
    ],
)
def test_stock_rejects_invalid_settlement(size, traits, diagnostic, pricing):
    with pytest.raises(ValueError, match=diagnostic):
        stock_quantity(ENTRY, size, traits, 1, pool_id="general_supplies", pricing=pricing)
    with pytest.raises(ValueError, match=diagnostic):
        tier_3_chance(UNIQUE, size, traits, pricing=pricing)
    with pytest.raises(ValueError, match=diagnostic):
        tier_3_limit(size, traits, 4, pricing=pricing)


def test_military_stock_rejects_unmapped_pool(pricing):
    with pytest.raises(ValueError, match="missing_pool"):
        stock_quantity(ENTRY, "city", ["military"], 1, pool_id="missing_pool", pricing=pricing)
