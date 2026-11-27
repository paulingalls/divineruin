import json
import re
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from economy_pricing import parse_economy_pricing
from sale_pricing import get_inventory_pools, merchant_gold_allocation, quote_sale, validate_npc_pool_bindings

ROOT = Path(__file__).parents[3]


def authored(file: str) -> list[dict]:
    return json.loads((ROOT / "content" / file).read_text())


def catalog_rows(rows: list[dict]) -> list[dict]:
    return [{"id": row["id"], "data": row} for row in rows]


CASES = json.loads((ROOT / "packages/shared/fixtures/sale-price-cases.json").read_text())
assert CASES and len({case["id"] for case in CASES}) == len(CASES)


@pytest.fixture
def pool_lookup(monkeypatch):
    pools, items = authored("inventory_pools.json"), authored("items.json")

    async def fetch(query: str) -> list[dict]:
        rows = pools if query == "SELECT id, data FROM inventory_pools ORDER BY id" else items
        assert rows is pools or query == "SELECT id, data FROM items ORDER BY id"
        return [{"id": row["id"], "data": json.dumps(row)} for row in rows]

    connection = AsyncMock()
    connection.fetch.side_effect = fetch
    monkeypatch.setattr("db.get_pool", AsyncMock(return_value=connection))
    return pools


async def test_authored_npc_pool_bindings(pool_lookup):
    pools = await get_inventory_pools()
    assert {pool_id: pool["buys"] for pool_id, pool in pools.items()} == {
        "market_general": "all",
        "grimjaw_weapons": ["weapon", "armor", "shield", "ammunition"],
        "temple_supplies": ["consumable"],
        "millhaven_supplies": "all",
    }
    assert {pool_id: pool["buys_rarities"] for pool_id, pool in pools.items()} == {
        "market_general": ["common"],
        "grimjaw_weapons": ["common", "uncommon", "rare", "legendary"],
        "temple_supplies": ["common", "uncommon", "rare", "legendary"],
        "millhaven_supplies": ["common"],
    }
    npcs = authored("npcs.json")
    validate_npc_pool_bindings(catalog_rows(npcs), pools)
    assert {npc["id"]: npc["inventory_pool"] for npc in npcs if npc["inventory_pool"] is not None} == {
        "grimjaw_blacksmith": "grimjaw_weapons",
        "temple_warden_selene": "temple_supplies",
        "innkeeper_maren": "millhaven_supplies",
        "aelora_guildmaster_dara": "market_general",
    }


async def test_inventory_pool_lookup_rejects_invalid_buying_rules(pool_lookup):
    pool_lookup[0]["buys_rarities"] = ["unknown_rarity"]
    with pytest.raises(ValueError, match=r"market_general.*buys_rarities"):
        await get_inventory_pools()


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
async def test_sale_quote(case, pool_lookup):
    pools = await get_inventory_pools()
    pricing = parse_economy_pricing(authored("pricing.json")[0])
    if "npc" in case:
        npc = next(npc for npc in authored("npcs.json") if npc["id"] == case["npc"])
        pool = pools[npc["inventory_pool"]]
        pool["location"] = case.get("pool_location", pool["location"])
        pool["buys"] = case.get("pool_buys", pool["buys"])
        location = next((row for row in authored("locations.json") if row["id"] == pool["location"]), None)
        if location is not None:
            location.update(case.get("location_fields", {}))
        if "error" in case:
            with pytest.raises(ValueError, match=re.escape(case["error"])):
                merchant_gold_allocation(pool, location, pricing)
        else:
            assert merchant_gold_allocation(pool, location, pricing) == case["expected_allocation_sp"]
        return
    assert (
        quote_sale(
            case["item"],
            pricing,
            kind=case["kind"],
            disposition=case["disposition"],
            pool=pools[case["pool"]] if case["pool"] else None,
            pools=pools,
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
