"""Tainted stacks through deterministic public command transport."""

import json
import os
import random
from uuid import uuid4

import pytest
from acceptance.loot_harness import LootHarness
from acceptance.mawling_harness import MawlingHarness
from acceptance.seeds import seed_player_with_pools
from acceptance.voice_condition_harness import ScenarioModel
from livekit.agents import Agent, AgentSession
from sample_fixtures import make_mock_room, published_payloads

import db
from activity_tools import begin_activity
from db_inventory_snapshot import get_inventory_snapshot
from inventory_tools import transact
from repair_item import repair_item
from session_data import SessionData


@pytest.fixture
def mock_combat_agent_factory():
    return None


async def seed_stack(pool, pid, item, quantity, tainted, **metadata):
    await pool.execute(
        "INSERT INTO player_inventory(player_id,item_id,tainted,data) VALUES($1,$2,$3,$4::jsonb)",
        pid,
        item,
        tainted,
        json.dumps({"quantity": quantity, "equipped": False, **metadata}),
    )


async def rows(pool, pid):
    return [
        dict(r)
        for r in await pool.fetch(
            "SELECT item_id,tainted,data FROM player_inventory WHERE player_id=$1 ORDER BY item_id,tainted", pid
        )
    ]


async def assert_published(h):
    snapshot = await get_inventory_snapshot(h.players[0])
    events = [
        p for p in published_payloads(h.sd.room) if p["type"] == "inventory_updated" and p["player_id"] == h.players[0]
    ]
    assert events
    assert {k: events[-1][k] for k in snapshot} == snapshot


class InventoryHarness(MawlingHarness):
    async def start_inventory(self):
        self.pool = await db.get_pool()
        self.players = [f"taint_{uuid4().hex}"]
        self.encounter_id = "ruins_mawling_pair"
        await seed_player_with_pools(self.pool, player_id=self.players[0], class_="warrior")
        await self.pool.execute(
            "INSERT INTO skill_advancement(player_id,skill_id,tier) VALUES($1,'crafting','expert')", self.players[0]
        )
        self.sd = SessionData(player_id=self.players[0], location_id="accord_guild_hall", room=make_mock_room())
        self.model = ScenarioModel([])
        self.session = AgentSession(llm=self.model, max_tool_steps=5, userdata=self.sd)
        await self.session.start(
            Agent(instructions="Execute the command.", tools=[transact, begin_activity, repair_item])
        )
        return self


@pytest.mark.parametrize(
    "creature,skill,seed,item,clean,tainted",
    [
        ("hollowed_scout", "crafting", 122, "rend_shard", 2, 1),
        ("grey_wolf", "survival", 1, "wolf_pelt", 1, 0),
    ],
)
async def test_victory_preserves_drop_taint(reset_db_pool, creature, skill, seed, item, clean, tainted):
    h = LootHarness()
    try:
        await h.start_loot(creature, [{skill: "expert"}], 1)
        if tainted:
            await seed_stack(h.pool, h.players[0], item, 2, False)
        await h.victory(random.Random(seed))
        actual = await rows(h.pool, h.players[0])
        stacks = [(r["tainted"], json.loads(r["data"])["quantity"]) for r in actual if r["item_id"] == item]
        assert stacks == ([(False, clean), (True, tainted)] if tainted else [(False, clean)])
        await assert_published(h)
    finally:
        await h.close()


async def test_transact_selects_clean_through_exhaustion(reset_db_pool):
    h = await InventoryHarness().start_inventory()
    try:
        pid = h.players[0]
        await seed_stack(h.pool, pid, "rend_shard", 2, False)
        await seed_stack(h.pool, pid, "rend_shard", 7, True, provenance="unchanged")
        original = (await rows(h.pool, pid))[1]
        for delta, expected in [(-1, 1), (-1, 0)]:
            await h.command("transact", {"item_id": "rend_shard", "delta": delta, "source": "test loss"})
            actual = await rows(h.pool, pid)
            assert actual[-1] == original
            assert len(actual) == (2 if expected else 1)
            if expected:
                assert json.loads(actual[0]["data"])["quantity"] == expected
            await assert_published(h)
        before = await get_inventory_snapshot(pid)
        error = await h.command("transact", {"item_id": "rend_shard", "delta": -1, "source": "test loss"}, error=True)
        assert "not in inventory" in error
        assert await get_inventory_snapshot(pid) == before
    finally:
        await h.close()


@pytest.mark.parametrize(
    "allow,clean,tainted,expected",
    [(False, 0, 3, None), (False, 3, 2, [(True, 2)]), (True, 2, 2, [(False, 1)])],
)
async def test_craft_recipe_stack_policy(reset_db_pool, allow, clean, tainted, expected):
    import recipes

    h = await InventoryHarness().start_inventory()
    recipe_id = f"taint_recipe_{uuid4().hex}"
    try:
        pid = h.players[0]
        base_recipe = await recipes.get_recipe("wooden_club")
        assert base_recipe is not None
        recipe = dict(base_recipe)
        recipe.update(
            id=recipe_id,
            tainted_materials=allow,
            materials=[{"material_id": "oak_wood", "quantity": 3, "tier_minimum": 1, "substitutable": False}],
        )
        await h.pool.execute("INSERT INTO recipes(id,data) VALUES($1,$2::jsonb)", recipe_id, json.dumps(recipe))
        await h.pool.execute(
            "INSERT INTO player_known_recipes(player_id,recipe_id,learned_via) VALUES($1,$2,'experimentation')",
            pid,
            recipe_id,
        )
        await seed_stack(h.pool, pid, "oak_wood", tainted, True)
        if clean:
            await seed_stack(h.pool, pid, "oak_wood", clean, False)
        before = await get_inventory_snapshot(pid)
        result = await h.command(
            "begin_activity", {"activity": {"kind": "crafting", "recipe_id": recipe_id}}, error=expected is None
        )
        if expected:
            actual = await rows(h.pool, pid)
            assert [(r["tainted"], json.loads(r["data"])["quantity"]) for r in actual] == expected
            assert result["activity_id"]
            await assert_published(h)
        else:
            assert "have 0 usable" in result
            assert await get_inventory_snapshot(pid) == before
            assert await h.pool.fetchval("SELECT count(*) FROM async_activities WHERE player_id=$1", pid) == 0
    finally:
        await h.pool.execute("DELETE FROM async_activities WHERE player_id=$1", h.players[0])
        await h.close()
        await h.pool.execute("DELETE FROM recipes WHERE id=$1", recipe_id)


async def test_repair_targets_clean_gear_only(reset_db_pool):
    h = await InventoryHarness().start_inventory()
    try:
        h.sd.location_id = "accord_forge"
        pid = h.players[0]
        await h.pool.execute("UPDATE players SET data=data || '{\"gold\":100}'::jsonb WHERE player_id=$1", pid)
        await h.pool.execute(
            "INSERT INTO npc_dispositions(npc_id,player_id,data) VALUES('grimjaw_blacksmith',$1,'{\"disposition\":\"friendly\"}')",
            pid,
        )
        for tainted, hits in [(False, 3), (True, 2)]:
            await seed_stack(h.pool, pid, "shortsword_basic", 1, tainted, current_hits=hits)
        original = (await rows(h.pool, pid))[1]
        await h.command("repair_item", {"item_id": "shortsword_basic", "npc_id": "grimjaw_blacksmith"})
        actual = await rows(h.pool, pid)
        assert actual[1] == original
        assert json.loads(actual[0]["data"])["current_hits"] == 10
        await h.pool.execute(
            "DELETE FROM player_inventory WHERE player_id=$1 AND item_id='shortsword_basic' AND NOT tainted", pid
        )
        before = await get_inventory_snapshot(pid)
        inventory = await rows(h.pool, pid)
        gold = await h.pool.fetchval("SELECT data->'gold' FROM players WHERE player_id=$1", pid)
        error = await h.command(
            "repair_item", {"item_id": "shortsword_basic", "npc_id": "grimjaw_blacksmith"}, error=True
        )
        assert "aren't carrying" in error
        assert await get_inventory_snapshot(pid) == before
        assert await rows(h.pool, pid) == inventory
        assert await h.pool.fetchval("SELECT data->'gold' FROM players WHERE player_id=$1", pid) == gold
    finally:
        await h.close()


async def test_ordered_pool_keeps_same_id_provenance(reset_db_pool, tmp_path, monkeypatch):
    import creature_schema

    catalog = tmp_path / "loot_tables.json"
    tables = json.loads(creature_schema.LOOT_CATALOG.read_text())
    h = LootHarness()
    prefix = f"taint_loot_{uuid4().hex}"
    creatures = [f"{prefix}_{i}" for i in range(3)]
    pool = await db.get_pool()
    base = json.loads(await pool.fetchval("SELECT data FROM creatures WHERE id='grey_wolf'"))
    try:
        for i, creature in enumerate(creatures):
            table = {
                "id": creature,
                "description": "Provenance fixture",
                "hollow_residue": i == 1,
                "drops": [{"item_id": "rend_shard", "chance": 1.0, "quantity": i + 1}],
            }
            tables.append(table)
            await pool.execute("INSERT INTO loot_tables(id,data) VALUES($1,$2::jsonb)", creature, json.dumps(table))
            await pool.execute(
                "INSERT INTO creatures(id,data) VALUES($1,$2::jsonb)",
                creature,
                json.dumps({**base, "id": creature, "loot_table_id": creature}),
            )
        catalog.write_text(json.dumps(tables))
        monkeypatch.setattr(creature_schema, "LOOT_CATALOG", catalog)
        await h.start_loot(creatures, [{}, {}], 3)
        await h.victory(random.Random(1))
        for index, expected in enumerate([[(False, 4)], [(True, 2)]]):
            actual = await rows(pool, h.players[index])
            assert [(r["tainted"], json.loads(r["data"])["quantity"]) for r in actual] == expected
        await assert_published(h)
    finally:
        if hasattr(h, "session"):
            await h.close()
        for creature in creatures:
            await pool.execute("DELETE FROM creatures WHERE id=$1", creature)
            await pool.execute("DELETE FROM loot_tables WHERE id=$1", creature)


@pytest.mark.parametrize("matched,allow", [(True, False), (True, True), (False, False)])
async def test_experiment_recipe_or_clean_default(reset_db_pool, matched, allow):
    import recipes

    h = await InventoryHarness().start_inventory()
    recipe_id = f"taint_experiment_{uuid4().hex}"
    cache = await db.get_redis() if os.environ.get("REDIS_URL") else None
    try:
        pid = h.players[0]
        base = await recipes.get_recipe("wooden_club")
        assert base is not None
        recipe = {
            **base,
            "id": recipe_id,
            "output_item": recipe_id,
            "crafting_dc": 100,
            "tainted_materials": allow,
            "materials": [{"material_id": "oak_wood", "quantity": 3, "tier_minimum": 1, "substitutable": False}],
        }
        await h.pool.execute("INSERT INTO recipes(id,data) VALUES($1,$2::jsonb)", recipe_id, json.dumps(recipe))
        if cache:
            await cache.delete("recipes:all")
        await seed_stack(h.pool, pid, "oak_wood", 2 if allow else 3, True)
        if allow:
            await seed_stack(h.pool, pid, "oak_wood", 2, False)
        before = await get_inventory_snapshot(pid)
        result = await h.command(
            "begin_activity",
            {
                "activity": {
                    "kind": "experiment",
                    "materials": [{"material_id": "oak_wood", "quantity": 3}],
                    "intended_output": recipe_id if matched else recipe_id + "_unknown",
                }
            },
            error=not allow,
        )
        if allow:
            actual = await rows(h.pool, pid)
            assert [(r["tainted"], json.loads(r["data"])["quantity"]) for r in actual] == [(False, 1)]
            assert result["outcome"] == "failure"
            await assert_published(h)
        else:
            assert "material" in result.lower()
            assert await get_inventory_snapshot(pid) == before
    finally:
        await h.close()
        await h.pool.execute("DELETE FROM recipes WHERE id=$1", recipe_id)
        if cache:
            await cache.delete("recipes:all", f"recipe:{recipe_id}")
