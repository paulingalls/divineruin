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


def test_masterwork_rotation_matches_the_standard_weapons() -> None:
    items = catalog_rows(authored("items.json"))
    by_id = {row["id"]: row["data"] for row in items}
    pools = parse_inventory_pools(catalog_rows(authored("inventory_pools.json")), items)
    weapons = [pools[f"weapons_armor_{grade}"] for grade in ("basic", "quality")]
    variants = CASES["masterwork_variants"]
    standard = {
        row["item_id"] for pool in weapons for row in pool["tier_2_items"] if by_id[row["item_id"]]["type"] == "weapon"
    }
    assert len(variants) == len(set(variants.values())) == 15
    assert standard == variants.keys()
    rotation = [
        row for pool in weapons for row in pool["tier_3_items"] if row.get("rotation_group") == "masterwork_weapons"
    ]
    assert sorted(row["item_id"] for row in rotation) == sorted(variants.values())
    for row in rotation:
        assert row["settlements"] == ["city", "capital"]
        assert row["presence_chance"] == 1
        assert row["restock_check"] == "weekly"
    for base_id, variant_id in variants.items():
        base, variant = by_id[base_id], by_id[variant_id]
        assert validate_weapon_profile(variant_id, variant) == validate_weapon_profile(base_id, base)
        assert variant["damage_bonus"] == 1
        assert "well-balanced" in variant["description"]
        assert variant["value_base"] > base["value_base"]
        for field in ("damage_dice", "properties"):
            assert variant[field] == base[field]
        assert variant["effects"] == base["effects"]


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
