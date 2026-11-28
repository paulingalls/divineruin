import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from economy_pricing import parse_economy_pricing
from inventory_pools import bound_inventory_pools, parse_inventory_pools
from sale_pricing import merchant_gold_allocation, quote_sale

ROOT = Path(__file__).parents[3]


def authored(file: str) -> list[dict]:
    return json.loads((ROOT / "content" / file).read_text())


def catalog_rows(rows: list[dict]) -> list[dict]:
    return [{"id": row["id"], "data": row} for row in rows]


CASES = json.loads((ROOT / "packages/shared/fixtures/sale-price-cases.json").read_text())
assert CASES and len({case["id"] for case in CASES}) == len(CASES)


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_sale_quote(case):
    npcs = authored("npcs.json")
    pools = parse_inventory_pools(catalog_rows(authored("inventory_pools.json")), catalog_rows(authored("items.json")))
    pricing = parse_economy_pricing(authored("pricing.json")[0])
    if "npc" in case:
        npc = next(npc for npc in npcs if npc["id"] == case["npc"])
        pool = pools[npc["inventory_pool"]]
        location_id = case["trade_location"]
        pool["merchant_kind"] = case.get("pool_merchant_kind", pool["merchant_kind"])
        pool["buys"] = case.get("pool_buys", pool["buys"])
        location = next((row for row in authored("locations.json") if row["id"] == location_id), None)
        if location is not None:
            location.update(case.get("location_fields", {}))
        if "error" in case:
            with pytest.raises(ValueError, match=re.escape(case["error"])):
                merchant_gold_allocation(pool, location, pricing, location_id=location_id)
        else:
            assert (
                merchant_gold_allocation(pool, location, pricing, location_id=location_id)
                == case["expected_allocation_sp"]
            )
        return
    assert (
        quote_sale(
            case["item"],
            pricing,
            kind=case["kind"],
            disposition=case["disposition"],
            pool=pools[case["pool"]] if case["pool"] else None,
            pools=bound_inventory_pools(catalog_rows(npcs), pools),
        )
        == case["expected"]
    )


@pytest.mark.parametrize(
    "path,value",
    [
        ("merchant_gold_sp", None),
        ("merchant_gold_sp.city", []),
        ("merchant_gold_sp.city.exotic", "200"),
        ("merchant_gold_sp.city.exotic", True),
        ("merchant_gold_sp.city.exotic", 1.5),
        ("merchant_gold_sp.city.exotic", -1),
        ("merchant_gold_sp.city.exotic", 2**53),
        ("merchant_gold_personality_multipliers", None),
        ("merchant_gold_personality_multipliers.military.arms", 0),
        ("merchant_gold_personality_multipliers.devout", float("inf")),
        ("merchant_gold_personality_multipliers.refuge", 0.12345),
    ],
)
def test_economy_parser_rejects_malformed_merchant_pricing(path, value):
    pricing = authored("pricing.json")[0]
    data = pricing
    *parents, field = path.split(".")
    for parent in parents:
        data = data[parent]
    data[field] = value
    with pytest.raises(ValueError, match=re.escape(path)):
        parse_economy_pricing(pricing)


@pytest.mark.parametrize(
    "path,missing",
    [
        ("merchant_gold_sp", "town"),
        ("merchant_gold_sp.city", "black_market"),
        ("merchant_gold_personality_multipliers", "prosperous"),
        ("merchant_gold_personality_multipliers.military", "other"),
    ],
)
def test_economy_parser_requires_all_merchant_pricing_fields(path, missing):
    pricing = authored("pricing.json")[0]
    data = pricing
    for parent in path.split("."):
        data = data[parent]
    del data[missing]
    with pytest.raises(ValueError, match=re.escape(path)):
        parse_economy_pricing(pricing)
    data["unknown"] = 1
    with pytest.raises(ValueError, match=re.escape(path)):
        parse_economy_pricing(pricing)


STOCK_CASES = json.loads((ROOT / "packages/shared/fixtures/stock-matrix-cases.json").read_text())


def matrix_gold_cases() -> Iterator[tuple[str, str | list[str], int, int | None]]:
    for size, row in STOCK_CASES["matrix"].items():
        for trait, general, arms in zip(STOCK_CASES["columns"], row["generalGold"], row["armsGold"], strict=True):
            yield size, trait, general, arms
    for trait, row in STOCK_CASES["additionalM62Traits"].items():
        yield "city", trait, row["generalGold"], row["armsGold"]
    for row in STOCK_CASES["combinedGold"]:
        yield "city", row["traits"], row["generalGold"], row["armsGold"]


@pytest.mark.parametrize("size,traits,general,arms", list(matrix_gold_cases()))
def test_merchant_gold_matrix(size, traits, general, arms):
    pools = parse_inventory_pools(catalog_rows(authored("inventory_pools.json")), catalog_rows(authored("items.json")))
    pricing = parse_economy_pricing(authored("pricing.json")[0])
    location = {"settlement_tier": size, "personality": traits}
    assert merchant_gold_allocation(pools["general_supplies"], location, pricing, location_id=size) == general
    if arms is None:
        with pytest.raises(ValueError, match=r"merchant_gold_sp\.hamlet\.specialist is unavailable"):
            merchant_gold_allocation(pools["weapons_armor_basic"], location, pricing, location_id=size)
    else:
        assert merchant_gold_allocation(pools["weapons_armor_basic"], location, pricing, location_id=size) == arms


def test_capital_specialty_purses():
    pools = parse_inventory_pools(catalog_rows(authored("inventory_pools.json")), catalog_rows(authored("items.json")))
    pricing = parse_economy_pricing(authored("pricing.json")[0])
    location = {"settlement_tier": "capital", "personality": "scholarly"}
    for pool_id, expected in [
        ("general_supplies", 500),
        ("weapons_armor_basic", 1000),
        ("exotic_goods", 1500),
        ("black_market", 800),
    ]:
        assert merchant_gold_allocation(pools[pool_id], location, pricing, location_id="capital") == expected


def test_merchant_gold_composes_without_losing_multiplier_precision():
    pools = parse_inventory_pools(catalog_rows(authored("inventory_pools.json")), catalog_rows(authored("items.json")))
    data = authored("pricing.json")[0]
    data["merchant_gold_sp"]["city"]["general"] = 100_000
    data["merchant_gold_personality_multipliers"].update(prosperous=1.1111, trade_hub=1.1111)
    pricing = parse_economy_pricing(data)
    location = {"settlement_tier": "city", "personality": ["prosperous", "trade_hub"]}
    assert merchant_gold_allocation(pools["general_supplies"], location, pricing, location_id="city") == 123_454


@pytest.mark.parametrize("pool_id", ["general_supplies", "weapons_armor_basic", "exotic_goods", "black_market"])
@pytest.mark.parametrize("traits", [*STOCK_CASES["columns"], *(row["traits"] for row in STOCK_CASES["combinedGold"])])
def test_keldaran_hold_gold_matches_city(pool_id, traits):
    pools = parse_inventory_pools(catalog_rows(authored("inventory_pools.json")), catalog_rows(authored("items.json")))
    pricing = parse_economy_pricing(authored("pricing.json")[0])
    hold = {"settlement_tier": "keldaran_hold", "personality": traits}
    city = {"settlement_tier": "city", "personality": traits}
    assert merchant_gold_allocation(pools[pool_id], hold, pricing, location_id="hold") == merchant_gold_allocation(
        pools[pool_id], city, pricing, location_id="city"
    )
