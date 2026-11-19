"""Authored encounter discovery through authenticated public tools."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from acceptance.mawling_harness import MawlingHarness
from sample_fixtures import CONTENT_ROOT, published_payloads

import event_types as E
from combat_agent import CombatAgent


@pytest.fixture
def mock_combat_agent_factory():
    return None


async def listed(h):
    result = await h.command("query_info", {"kind": "creature"})
    assert isinstance(result["creatures"], list)
    entries = result["encounter_templates"]
    assert entries == sorted(entries, key=lambda row: row["id"])
    return {row["id"]: row for row in entries}


async def set_level(conn, pid, n):
    await conn.execute("UPDATE players SET data=jsonb_set(data,'{level}',$2::jsonb) WHERE player_id=$1", pid, str(n))


async def put(conn, table, key, data):
    sql = f"INSERT INTO {table}(id,data) VALUES ($1,$2::jsonb) ON CONFLICT(id) DO UPDATE SET data=excluded.data"
    await conn.execute(sql, key, json.dumps(data))


async def test_party_discovery_to_combat(reset_db_pool):
    h = MawlingHarness()
    try:
        await h.prepare((1, 1), companion=None)
        low = await listed(h)
        assert "shadeling_cluster" in low and "hollowmoth_swarm" not in low
        await set_level(h.pool, h.players[1], 5)
        entries = await listed(h)
        assert "hollowed_scout" not in entries
        swarm = entries["hollowmoth_swarm"]
        template = json.loads(await h.pool.fetchval("SELECT data FROM encounter_templates WHERE id=$1", swarm["id"]))
        species_id = template["enemies"][0]["creature_id"]
        creature = json.loads(await h.pool.fetchval("SELECT data FROM creatures WHERE id=$1", species_id))
        description = creature["narration"]["first_sighting"].split(". ")[0].rstrip(".") + "."
        assert swarm == dict(id=template["id"], difficulty=template["difficulty"], description=description)
        await h.command("enter_mode", {"mode": "combat", "encounter_id": swarm["id"]})
        assert isinstance(h.session.current_agent, CombatAgent)
        state = await h.reload()
        assert state.encounter_id == swarm["id"]
        assert {(p.id, p.creature_id, p.role) for p in state.participants if p.type == "enemy"} == {
            (e["id"], e["creature_id"], e["role"]) for e in template["enemies"]
        }
        starts = [p["encounter_id"] for p in published_payloads(h.sd.room) if p["type"] == E.COMBAT_STARTED]
        assert swarm["id"] in starts
    finally:
        await h.close()


async def test_authored_inventory_and_bindings(reset_db_pool):
    h = MawlingHarness()
    await h.prepare((20,), companion=None)
    async with h.pool.acquire() as conn:
        transaction = conn.transaction()
        await transaction.start()
        try:
            with patch("db.get_pool", AsyncMock(return_value=conn)):
                templates = [json.loads(r["data"]) for r in await conn.fetch("SELECT data FROM encounter_templates")]
                creatures = {r["id"]: json.loads(r["data"]) for r in await conn.fetch("SELECT id,data FROM creatures")}
                bound = {"hollow_patrol_greyvale", "ruins_mawling_pair", "fragment_shadeling", "hollow_still"}
                unbound = {t["id"] for t in templates} - bound
                assert {"hollowmoth_swarm", "hollow_weaver_ambush", "hollow_mawling_pack", "hollow_choir"} <= unbound
                for template in templates:
                    species = [creatures[e["creature_id"]] for e in template["enemies"]]
                    regions = set.intersection(*(set(c["regions"]) for c in species))
                    terrains = set.intersection(*(set(c["terrains"]) for c in species))
                    assert regions and terrains
                    loc = "surface_" + template["id"]
                    await put(conn, "locations", loc, {"region": sorted(regions)[0], "terrain": sorted(terrains)[0]})
                    h.sd.location_id = loc
                    await set_level(conn, h.players[0], template["recommended_party_level"])
                    entries = await listed(h)
                    assert (template["id"] in entries) == (template["id"] in unbound)
                h.sd.location_id = "greyvale_wilderness_north"
                await set_level(conn, h.players[0], 20)
                assert "shadeling_cluster" in await listed(h)
                quest = {"stages": [{"completion_conditions": {"encounter": "shadeling_cluster"}}]}
                await put(conn, "quests", "surface_binding", quest)
                assert "shadeling_cluster" not in await listed(h)
                await conn.execute("DELETE FROM quests WHERE id='surface_binding'")
                for text, excluded in [
                    ('hollow_wisp encounter_id="shadeling_cluster_extra"', False),
                    ('encounter_id="shadeling_cluster"', True),
                    ('encounter_id=\\"shadeling_cluster\\"', True),
                ]:
                    await put(conn, "scenes", "surface_binding", {"beats": [{"hint": text}]})
                    entries = await listed(h)
                    assert "hollow_wisp" in entries and ("shadeling_cluster" not in entries) == excluded
                await conn.execute("DELETE FROM scenes WHERE id='surface_binding'")
                mixed = dict(templates[0], id="surface_mixed", recommended_party_level=1)
                mixed["enemies"] = [{"creature_id": "hollow_shadeling"}, {"creature_id": "bandit"}]
                await put(conn, "encounter_templates", mixed["id"], mixed)
                assert "surface_mixed" in await listed(h)
                for field, values in [("terrains", ["city"]), ("regions", ["ashmark"])]:
                    await put(conn, "creatures", "bandit", {**creatures["bandit"], field: values})
                    entries = await listed(h)
                    assert "shadeling_cluster" in entries and "surface_mixed" not in entries
                    await put(conn, "creatures", "bandit", creatures["bandit"])
                mixed["enemies"] = [{"creature_id": "no_such_species"}]
                await put(conn, "encounter_templates", mixed["id"], mixed)
                error = await h.command("query_info", {"kind": "creature"}, error=True)
                assert "surface_mixed" in error and "no_such_species" in error
                await conn.execute("DELETE FROM encounter_templates WHERE id='surface_mixed'")
                sql = "UPDATE encounter_templates SET data=jsonb_set(data,'{recommended_party_level}','20')"
                await conn.execute(sql)
                await set_level(conn, h.players[0], 1)
                assert await listed(h) == {}
        finally:
            await transaction.rollback()
            await h.close()


async def test_shipped_boss_discovery(reset_db_pool):
    from acceptance._catalog_cutover_helpers import assert_strength

    locations = json.loads((CONTENT_ROOT / "content/locations.json").read_text())
    front = next(r for r in locations if r["id"] == "ashmark_corrupted_front")
    north = next(r for r in locations if r["id"] == "greyvale_wilderness_north")
    assert north["exits"]["northwest"]["destination"] == front["id"]
    assert front["exits"]["southeast"]["destination"] == north["id"]
    catalog = {r["id"]: r for r in json.loads((CONTENT_ROOT / "content/creatures.json").read_text())}
    for boss in ("hollow_veilrender_boss", "hollow_knight_boss"):
        h = MawlingHarness()
        try:
            await h.prepare((14, 14), companion=None, location=front["id"])
            discovery = await h.command("query_info", {"kind": "creature"})
            entry = next(r for r in discovery["encounter_templates"] if r["id"] == boss)
            assert entry["recommended_party_size"] == 2
            result = await h.command("enter_mode", {"mode": "combat", "encounter_id": entry["id"]})
            state = await h.reload()
            assert state.encounter_id == boss
            if boss == "hollow_veilrender_boss":
                source = next(p for p in state.participants if p.type == "enemy")
                assert source.regeneration and source.corruption_field
                assert (source.hp_max, source.ac, source.role) == (120, 14, "standard")
                template = json.loads(await h.pool.fetchval("SELECT data FROM encounter_templates WHERE id=$1", boss))
                assert_strength(template, catalog)
                assert {"Reality Crush", "Corruption Pulse"} <= set(
                    next(p for p in result["participants"] if p["id"] == source.id)["actions"]
                )
        finally:
            await h.close()
