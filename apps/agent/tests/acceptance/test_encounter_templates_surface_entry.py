"""Authored encounter discovery through authenticated public tools."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from acceptance.mawling_harness import MawlingHarness
from sample_fixtures import published_payloads

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


async def test_party_discovery_to_combat(reset_db_pool):
    h = MawlingHarness()
    try:
        await h.prepare((1, 1), companion=None)
        low = await listed(h)
        assert "shadeling_cluster" in low
        assert "hollowmoth_swarm" not in low
        await h.pool.execute("UPDATE players SET data=jsonb_set(data,'{level}','5') WHERE player_id=$1", h.players[1])
        entries = await listed(h)
        assert "hollowed_scout" not in entries
        swarm = entries["hollowmoth_swarm"]
        template = json.loads(await h.pool.fetchval("SELECT data FROM encounter_templates WHERE id=$1", swarm["id"]))
        creature = json.loads(
            await h.pool.fetchval("SELECT data FROM creatures WHERE id=$1", template["enemies"][0]["creature_id"])
        )
        assert swarm == {
            "id": template["id"],
            "difficulty": template["difficulty"],
            "description": creature["narration"]["first_sighting"].split(". ")[0].rstrip(".") + ".",
        }
        await h.command("enter_mode", {"mode": "combat", "encounter_id": swarm["id"]})
        assert isinstance(h.session.current_agent, CombatAgent)
        state = await h.reload()
        assert state.encounter_id == swarm["id"]
        assert {(p.id, p.creature_id, p.role) for p in state.participants if p.type == "enemy"} == {
            (e["id"], e["creature_id"], e["role"]) for e in template["enemies"]
        }
        assert any(
            p["type"] == E.COMBAT_STARTED and p["encounter_id"] == swarm["id"] for p in published_payloads(h.sd.room)
        )
    finally:
        await h.close()


async def test_authored_inventory_and_bindings(reset_db_pool):
    h = MawlingHarness()
    try:
        await h.prepare((20,), companion=None)
        async with h.pool.acquire() as conn, conn.transaction():
            with patch("db.get_pool", AsyncMock(return_value=conn)):
                templates = [json.loads(r["data"]) for r in await conn.fetch("SELECT data FROM encounter_templates")]
                creatures = {r["id"]: json.loads(r["data"]) for r in await conn.fetch("SELECT id,data FROM creatures")}
                bound = {"hollow_patrol_greyvale", "ruins_mawling_pair", "fragment_shadeling"}
                unbound = {t["id"] for t in templates} - bound
                assert {"hollowmoth_swarm", "hollow_weaver_ambush", "hollow_mawling_pack", "hollow_choir"} <= unbound
                for template in templates:
                    species = [creatures[e["creature_id"]] for e in template["enemies"]]
                    regions = set.intersection(*(set(c["regions"]) for c in species))
                    terrains = set.intersection(*(set(c["terrains"]) for c in species))
                    assert regions and terrains
                    location_id = "surface_" + template["id"]
                    await conn.execute(
                        "INSERT INTO locations(id,data) VALUES ($1,$2::jsonb)",
                        location_id,
                        json.dumps({"region": sorted(regions)[0], "terrain": sorted(terrains)[0]}),
                    )
                    h.sd.location_id = location_id
                    await conn.execute(
                        "UPDATE players SET data=jsonb_set(data,'{level}',$2::jsonb) WHERE player_id=$1",
                        h.players[0],
                        json.dumps(template["recommended_party_level"]),
                    )
                    entries = await listed(h)
                    assert (template["id"] in entries) == (template["id"] in unbound)
                h.sd.location_id = "greyvale_wilderness_north"
                await conn.execute(
                    "UPDATE players SET data=jsonb_set(data,'{level}','20') WHERE player_id=$1", h.players[0]
                )
                assert "shadeling_cluster" in await listed(h)
                quest = {"stages": [{"completion_conditions": {"encounter": "shadeling_cluster"}}]}
                await conn.execute(
                    "INSERT INTO quests(id,data) VALUES ('surface_binding',$1::jsonb)", json.dumps(quest)
                )
                assert "shadeling_cluster" not in await listed(h)
                await conn.execute("DELETE FROM quests WHERE id='surface_binding'")
                for text, excluded in [
                    ('hollow_wisp encounter_id="shadeling_cluster_extra"', False),
                    ('encounter_id="shadeling_cluster"', True),
                    ('encounter_id=\\"shadeling_cluster\\"', True),
                ]:
                    await conn.execute(
                        "INSERT INTO scenes(id,data) VALUES ('surface_binding',$1::jsonb) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                        json.dumps({"beats": [{"hint": text}]}),
                    )
                    entries = await listed(h)
                    assert "hollow_wisp" in entries
                    assert ("shadeling_cluster" not in entries) == excluded
                await conn.execute("DELETE FROM scenes WHERE id='surface_binding'")
                mixed = {
                    **templates[0],
                    "id": "surface_mixed",
                    "recommended_party_level": 1,
                    "enemies": [{"creature_id": "hollow_shadeling"}, {"creature_id": "bandit"}],
                }
                await conn.execute(
                    "INSERT INTO encounter_templates(id,data) VALUES ($1,$2::jsonb)", mixed["id"], json.dumps(mixed)
                )
                assert "surface_mixed" in await listed(h)
                for field, values in [("terrains", ["city"]), ("regions", ["ashmark"])]:
                    original = await conn.fetchval("SELECT data FROM creatures WHERE id='bandit'")
                    await conn.execute(
                        "UPDATE creatures SET data=jsonb_set(data,ARRAY[$1],$2::jsonb) WHERE id='bandit'",
                        field,
                        json.dumps(values),
                    )
                    entries = await listed(h)
                    assert "shadeling_cluster" in entries and "surface_mixed" not in entries
                    await conn.execute("UPDATE creatures SET data=$1::jsonb WHERE id='bandit'", original)
                mixed["enemies"] = [{"creature_id": "no_such_species"}]
                await conn.execute(
                    "UPDATE encounter_templates SET data=$1::jsonb WHERE id='surface_mixed'", json.dumps(mixed)
                )
                error = await h.command("query_info", {"kind": "creature"}, error=True)
                assert "surface_mixed" in error and "no_such_species" in error
                await conn.execute("DELETE FROM encounter_templates WHERE id='surface_mixed'")
                await conn.execute(
                    "UPDATE encounter_templates SET data=jsonb_set(data,'{recommended_party_level}','20')"
                )
                await conn.execute(
                    "UPDATE players SET data=jsonb_set(data,'{level}','1') WHERE player_id=$1", h.players[0]
                )
                assert await listed(h) == {}
                raise RollbackSurface()
    except RollbackSurface:
        pass
    finally:
        await h.close()


class RollbackSurface(Exception):
    pass
