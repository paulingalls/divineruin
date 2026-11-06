import asyncio
import json
from pathlib import Path
from random import Random

import asyncpg
import pytest

from materials import parse_material_row

# Bestiary Harvesting Skill Requirements (:1173-1183); kind is finer than category.
KIND_PAIRS = {
    "pelt": ("survival", "trained"),
    "meat": ("survival", "trained"),
    "basic_organ": ("survival", "trained"),
    "plant": ("survival", "trained"),
    "venom": ("survival", "expert"),
    "gland": ("survival", "expert"),
    "rare_organ": ("survival", "expert"),
    "rare_gem": ("survival", "expert"),
    "construct_part": ("crafting", "trained"),
    "hollow_residue": ("crafting", "expert"),
    "volatile": ("crafting", "expert"),
    "magical_component": ("arcana", "trained"),
    "named_fragment": ("arcana", "expert"),
    "high_tier_arcane": ("arcana", "expert"),
    "veil_shard": ("arcana", "expert"),
}

KIND_ITEMS = {
    "pelt": {
        "wolf_pelt": "hide",
        "boar_hide": "hide",
        "stalker_pelt": "hide",
        "bison_hide": "hide",
        "viper_skin": "hide",
        "cave_wyrm_scales": "scale",
        "lurker_hide": "hide",
        "eel_skin": "hide",
        "dire_bear_hide": "hide",
        "troll_hide": "hide",
    },
    "meat": {
        "wolf_meat": "monster_part",
        "boar_meat": "monster_part",
        "bison_meat": "reagent",
        "dire_bear_fat": "monster_part",
        "eel_oil": "reagent",
    },
    "basic_organ": {"spider_silk": "fiber", "razorwing_talons": "monster_part"},
    "plant": {"ironwood_bark": "wood"},
    "venom": {"venom_sac": "monster_part", "viper_venom": "reagent"},
    "gland": {
        "wyrm_acid_gland": "monster_part",
        "lightning_gland": "monster_part",
        "paralytic_gland": "monster_part",
        "lightning_gland_large": "monster_part",
    },
    "rare_organ": {"dire_bear_heart": "monster_part", "troll_blood": "monster_part"},
    "rare_gem": {"thornveld_amber": "gem", "cave_gemstone": "gem"},
    "construct_part": {
        "golem_core": "arcane",
        "forged_steel": "metal",
        "guardian_core_small": "monster_part",
        "ancient_mechanism": "monster_part",
    },
    "hollow_residue": {
        "hollow_residue_t1": "hollow_residue",
        "rend_shard": "hollow_residue",
        "hollow_residue_t2": "hollow_residue",
        "wrack_core": "hollow_residue",
        "dissolution_membrane": "hollow_residue",
        "spatial_residue": "hollow_residue",
        "woven_void_fragment": "hollow_residue",
        "wrack_core_large": "hollow_residue",
    },
    "volatile": {"corrupted_heartwood": "wood", "living_stone": "stone"},
    "magical_component": {"remnant_identity": "arcane", "storm_crystal": "monster_part"},
    "named_fragment": {
        "named_fragment": "hollow_residue",
        "architect_blueprint_fragment": "arcane",
        "void_touched_foundation": "hollow_residue",
    },
    "high_tier_arcane": {"power_crystal": "arcane", "choir_resonance_crystal": "arcane"},
    "veil_shard": {"veil_shard": "hollow_residue"},
}


@pytest.fixture(scope="module")
def catalog(migrated_db):
    async def read():
        conn = await asyncpg.connect(migrated_db)
        try:
            result = {}
            for table in ("loot_tables", "materials_catalog", "items", "recipes"):
                rows = await conn.fetch(f"SELECT id, data FROM {table}")
                assert rows, table
                result[table] = {row["id"]: json.loads(row["data"]) for row in rows}
            return result
        finally:
            await conn.close()

    return asyncio.run(read())


def owned_drops(catalog):
    drops = {}
    for table in catalog["loot_tables"].values():
        for drop in table["drops"]:
            item_id = drop["item_id"]
            owners = [catalog[name][item_id] for name in ("materials_catalog", "items") if item_id in catalog[name]]
            assert len(owners) == 1, (table["id"], item_id, owners)
            drops[item_id] = owners[0]
    assert drops
    return drops


def test_harvest_kinds_match_spec_and_category(catalog):
    owners = owned_drops(catalog)
    expected = {item: (kind, category) for kind, items in KIND_ITEMS.items() for item, category in items.items()}
    gated = set()
    for table in catalog["loot_tables"].values():
        for drop in table["drops"]:
            if drop.get("requires"):
                item_id = drop["item_id"]
                owner = owners[item_id]
                kind, category = expected[item_id]
                assert owner.get("kind") == kind, (table["id"], item_id, owner.get("kind"), kind)
                assert owner.get("category", owner.get("material_category")) == category, item_id
                skill, tier = KIND_PAIRS[kind]
                assert drop["requires"] == [{"skill": skill, "tier": tier}], (table["id"], item_id)
                gated.add(item_id)
    assert gated
    assert gated == set(expected)


def test_cave_gemstone_uses_survival_expert(catalog):
    drops = catalog["loot_tables"]["loot_cave_wyrm"]["drops"]
    cave = next(drop for drop in drops if drop["item_id"] == "cave_gemstone")
    assert cave["requires"] == [{"skill": "survival", "tier": "expert"}]


def test_material_defaults_and_real_parser(catalog):
    materials = catalog["materials_catalog"]
    for item_id, row in materials.items():
        assert parse_material_row(item_id, row) == {"id": item_id, "category": row["category"], "tier": row["tier"]}
    assert (materials["woven_void_fragment"]["tier"], materials["woven_void_fragment"]["category"]) == (
        2,
        "hollow_residue",
    )
    assert (materials["veil_shard"]["tier"], materials["veil_shard"]["category"]) == (3, "hollow_residue")


def test_salvage_is_equipment(catalog):
    materials = catalog["materials_catalog"]
    owners = owned_drops(catalog)
    salvage = owners["salvageable_weapon"]
    assert "salvageable_weapon" not in materials
    assert salvage["type"] == "equipment"
    assert salvage["tier"] == 3
    assert salvage["tags"] == ["equipment", "salvage"]
    assert salvage["effects"] == []
    assert salvage["value_base"] == 100


def test_every_drop_has_exactly_one_crafting_disposition(catalog):
    owners = owned_drops(catalog)
    linked = {req["material_id"] for recipe in catalog["recipes"].values() for req in recipe["materials"]}
    traded = {item_id for item_id, row in owners.items() if row.get("crafting_use") == "trade"}
    assert linked & owners.keys()
    assert traded
    for item_id in owners:
        assert (item_id in linked) != (item_id in traded), item_id


@pytest.fixture
def mock_combat_agent_factory():
    return None


CATEGORY_VICTORIES = [
    ("hollow", "hollow_shadeling", 1, {"hollow_residue_t1": 1}, 0),
    ("beast", "grey_wolf", 9, {"wolf_pelt": 1, "wolf_fangs": 4, "wolf_meat": 2}, 0),
    ("humanoid", "bandit", 9, {"shortsword_basic": 1}, 4),
    ("construct", "war_golem", 9, {"golem_core": 1, "enchanted_stone": 7, "forged_steel": 2}, 0),
    ("undead", "schema_undead", 9, {"healing_salve": 1}, 0),
    ("elemental", "corrupted_treant", 9, {"ironwood_bark": 4}, 0),
]


@pytest.mark.parametrize("category,creature,seed,expected,silver", CATEGORY_VICTORIES)
async def test_every_category_victory_loot(reset_db_pool, category, creature, seed, expected, silver):
    from acceptance.loot_harness import LootHarness

    import db
    import db_queries
    from creature_schema import CATEGORIES

    assert {case[0] for case in CATEGORY_VICTORIES} == set(CATEGORIES)
    h = LootHarness()
    pool = await db.get_pool()
    if category == "undead":
        fixtures = json.loads(
            (Path(__file__).resolve().parents[4] / "packages/shared/fixtures/creature_blocks.json").read_text()
        )
        row = next(case["block"] for case in fixtures["valid"] if case["name"] == "synthetic_undead")
        await pool.execute("INSERT INTO creatures (id,data) VALUES ($1,$2::jsonb)", row["id"], json.dumps(row))
    try:
        await h.start_loot(creature, [{"crafting": "expert", "survival": "expert", "arcana": "expert"}], 1)
        assert (await h.reload()).participants
        await h.victory(Random(seed))
        records = await pool.fetch("SELECT item_id,data,tainted FROM player_inventory WHERE player_id=$1", h.players[0])
        actual = {r["item_id"]: json.loads(r["data"]) for r in records}
        assert {key: value["quantity"] for key, value in actual.items()} == expected
        assert expected
        assert all(r["tainted"] is (category == "hollow") for r in records)
        player = await db_queries.get_player(h.players[0])
        assert player is not None and player["gold"] == pytest.approx(silver / 10)
    finally:
        if hasattr(h, "session"):
            await h.close()
        elif hasattr(h, "encounter_id"):
            await pool.execute("DELETE FROM encounter_templates WHERE id=$1", h.encounter_id)
            for pid in h.players:
                await pool.execute("DELETE FROM players WHERE player_id=$1", pid)
        if category == "undead":
            await pool.execute("DELETE FROM creatures WHERE id=$1", creature)
