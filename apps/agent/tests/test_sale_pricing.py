import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from pricing_queries import _validate_economy_pricing
from sale_pricing import get_inventory_pools, quote_sale, validate_npc_pool_bindings

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
    monkeypatch.setattr("sale_pricing.db.get_pool", AsyncMock(return_value=connection))
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
    assert (
        quote_sale(
            case["item"],
            _validate_economy_pricing(authored("pricing.json")[0]),
            kind=case["kind"],
            disposition=case["disposition"],
            pool=pools[case["pool"]] if case["pool"] else None,
            pools=pools,
        )
        == case["expected"]
    )
