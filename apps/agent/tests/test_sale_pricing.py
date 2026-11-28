import json
import re
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
