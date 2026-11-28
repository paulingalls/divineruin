import json
import re
from copy import deepcopy

import pytest
from test_sale_pricing import ROOT, authored, catalog_rows

from inventory_pools import bound_inventory_pools, parse_inventory_pools
from weapon_proficiency import validate_weapon_profile

CASES = json.loads((ROOT / "packages/shared/fixtures/inventory-pool-cases.json").read_text())
LEGACY = json.loads((ROOT / "packages/shared/fixtures/legacy-inventory-pools.json").read_text())


def test_spec_pool_catalog():
    items = authored("items.json")
    pools = parse_inventory_pools(catalog_rows(authored("inventory_pools.json")), catalog_rows(items))
    assert pools == {row["id"]: row for row in CASES["pools"]}
    npcs = authored("npcs.json")
    assert {row["id"]: row["inventory_pool"] for row in npcs if row["inventory_pool"] is not None} == CASES[
        "npc_bindings"
    ]
    bound_inventory_pools(catalog_rows(npcs), pools)
    assert {row["id"]: row["inventory_pool"] for row in authored("role_archetypes.json")} == CASES["role_bindings"]

    by_id = {row["id"]: row for row in items}
    stocked = set()
    for pool in pools.values():
        ids = pool["tier_1_items"] + [row["item_id"] for row in pool["tier_2_items"] + pool["tier_3_items"]]
        for item_id in set(ids) & CASES["items"].keys():
            item = by_id[item_id]
            validate_weapon_profile(item_id, item)
            assert {key: item[key] for key in CASES["items"][item_id]} == CASES["items"][item_id]
            assert pool["buys"] == "all" or item["type"] in pool["buys"]
            assert item["rarity"] in pool["buys_rarities"]
            stocked.add(item_id)
    assert stocked == CASES["items"].keys()


@pytest.mark.parametrize("case", CASES["malformed"])
def test_pool_parser_refuses_malformed_entry(case):
    pools = authored("inventory_pools.json")
    source = deepcopy(next(row for row in pools if row["id"] == case["pool"]))
    target = source
    *parents, field = case["path"]
    for key in parents:
        target = target[key]
    if case["remove"]:
        del target[field]
    else:
        target[field] = case["value"]
    diagnostic = f"inventory_pools[{source['id']}]{case['diagnostic']}"
    with pytest.raises(ValueError, match=re.escape(diagnostic)):
        parse_inventory_pools(catalog_rows([source]), catalog_rows(authored("items.json")))


def test_pool_parser_refuses_flat_rows():
    pool = LEGACY["pools"][0]
    with pytest.raises(ValueError, match=rf"inventory_pools\[{pool['id']}\]\.(location|items|restock_interval_hours)"):
        parse_inventory_pools(catalog_rows([pool]), catalog_rows(authored("items.json")))


def test_pool_parser_refuses_empty_item_catalog():
    with pytest.raises(ValueError, match="items produced no rows"):
        parse_inventory_pools(catalog_rows(authored("inventory_pools.json")), [])
