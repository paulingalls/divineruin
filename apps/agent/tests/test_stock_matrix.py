import json
from pathlib import Path

import pytest

from economy_pricing import parse_economy_pricing
from inventory_pools import InventoryPoolTier2, InventoryPoolTier3, parse_inventory_pools
from stock_matrix import stock_quantity, stock_range, tier_3_chance, tier_3_limit

ROOT = Path(__file__).parents[3]
CASES = json.loads((ROOT / "packages/shared/fixtures/stock-matrix-cases.json").read_text())
FIXED: InventoryPoolTier2 = {
    "item_id": "spear_common",
    "quantity_by_settlement": {size: [12, 12] for size in ("hamlet", "village", "town", "city")},
}


@pytest.fixture(scope="module")
def economy() -> dict:
    return parse_economy_pricing(json.loads((ROOT / "content/pricing.json").read_text())[0])


@pytest.fixture(scope="module")
def pools() -> dict:
    return parse_inventory_pools(
        *(
            [{"id": row["id"], "data": row} for row in json.loads((ROOT / f"content/{table}.json").read_text())]
            for table in ("inventory_pools", "items")
        )
    )


@pytest.mark.parametrize("size", ["hamlet", "village", "town", "city", "capital"])
def test_stock_matrix(size, economy):
    columns = CASES["columns"]
    assert columns == ["prosperous", "struggling", "military", "trade_hub", "frontier", "corrupt"]
    assert set(CASES["matrix"]) == {"hamlet", "village", "town", "city", "capital"}
    row = CASES["matrix"][size]
    for key, pool in [("generalStock", "general_supplies"), ("armsStock", "weapons_armor_basic")]:
        assert [stock_quantity(FIXED, size, [trait], 12, pool_id=pool, pricing=economy) for trait in columns] == row[
            key
        ]


@pytest.mark.parametrize("trait", ["scholarly", "devout", "refuge"])
def test_other_m62_traits(trait, economy):
    row = CASES["additionalM62Traits"][trait]
    for key, pool in [("generalStock", "general_supplies"), ("armsStock", "weapons_armor_basic")]:
        assert stock_quantity(FIXED, "city", [trait], 12, pool_id=pool, pricing=economy) == row[key]


def test_authored_range_and_rounding(pools, economy):
    pool = pools["weapons_armor_basic"]
    spear = next(entry for entry in pool["tier_2_items"] if entry["item_id"] == "spear_common")
    for size, expected in [("village", [1, 3]), ("city", [3, 8]), ("keldaran_hold", [3, 8]), ("capital", [3, 8])]:
        assert stock_range(spear, size) == expected
    for size, traits, rolled, expected in [
        ("village", ["scholarly"], 3, 3),
        ("city", ["scholarly"], 8, 8),
        ("keldaran_hold", ["scholarly"], 8, 8),
        ("capital", ["scholarly"], 3, 4),
        ("capital", ["scholarly"], 8, 11),
        ("capital", ["prosperous"], 8, 13),
        ("village", ["trade_hub"], 2, 3),
        ("village", ["struggling"], 3, 2),
        ("village", ["prosperous", "military"], 2, 4),
        ("village", ["military", "prosperous"], 2, 4),
        ("city", ["struggling", "corrupt"], 3, 0),
    ]:
        assert stock_quantity(spear, size, traits, rolled, pool_id=pool["id"], pricing=economy) == expected
    assert (
        stock_quantity(FIXED, "city", ["prosperous", "frontier"], 12, pool_id="general_supplies", pricing=economy) == 8
    )


@pytest.mark.parametrize(
    "pool_id,expected",
    [
        ("weapons_armor_quality", 18),
        ("alchemical_supplies_common", 9),
        ("exotic_goods", 9),
        ("jeweler_goods", 9),
        ("temple_supplies", 12),
        ("black_market", 12),
    ],
)
def test_military_stock_for_other_pools(pool_id, expected, pools, economy):
    assert stock_quantity(FIXED, "city", ["military"], 12, pool_id=pools[pool_id]["id"], pricing=economy) == expected


@pytest.mark.parametrize(
    "size,traits,eligible,base,expected",
    [
        ("town", ["scholarly"], ["town"], 0.25, 0.25),
        ("city", ["prosperous"], ["city"], 0.25, 0.40),
        ("city", ["prosperous"], ["city"], 0.95, 1),
        ("city", ["struggling"], ["city"], 0.25, 0),
        ("city", ["prosperous", "frontier"], ["city"], 0.25, 0),
        ("hamlet", ["scholarly"], ["hamlet"], 0.25, 0),
        ("village", ["scholarly"], ["village"], 0.25, 0),
        ("town", ["scholarly"], ["city"], 0.25, 0),
        ("capital", ["scholarly"], ["city"], 0.25, 0),
        ("capital", ["devout"], ["capital"], 0.25, 0.25),
        ("keldaran_hold", ["refuge"], ["city"], 0.25, 0.25),
    ],
)
def test_tier_3_chance(size, traits, eligible, base, expected, economy):
    entry = InventoryPoolTier3(
        item_id="spear_common", settlements=eligible, presence_chance=base, restock_check="daily"
    )
    assert tier_3_chance(entry, size, traits, pricing=economy) == pytest.approx(expected)


@pytest.mark.parametrize(
    "size,traits,count,expected",
    [
        ("hamlet", ["scholarly"], 4, 0),
        ("village", ["scholarly"], 4, 0),
        ("town", ["scholarly"], 4, 2),
        ("town", ["scholarly"], 1, 1),
        ("city", ["scholarly"], 4, 4),
        ("capital", ["scholarly"], 4, 4),
        ("keldaran_hold", ["scholarly"], 4, 4),
        ("city", ["struggling"], 4, 0),
        ("city", ["prosperous", "frontier"], 4, 0),
    ],
)
def test_tier_3_slot_limit(size, traits, count, expected, economy):
    assert tier_3_limit(size, traits, count, pricing=economy) == expected
