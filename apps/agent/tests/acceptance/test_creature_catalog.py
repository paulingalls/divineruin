import asyncio
import importlib
import json
import sys
from pathlib import Path

import asyncpg
import pytest
from test_creature_spec_pins_encounter_authored import SIGNATURE_PINS

import db
from creature_catalog import CreatureNotFoundError, query_creature_by_id, query_creatures_by_region
from creature_schema import validate_creature_stat_block
from terrain import TerrainType

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))
seed_content = importlib.import_module("seed_content")


def assert_catalog_rows(rows):
    assert rows
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids))
    assert {"hollow_shadeling", "hollow_hollowmoth"} <= set(ids)
    for row in rows:
        data = json.loads(row["data"])
        assert isinstance(data["terrains"], list) and data["terrains"]
        assert all(isinstance(value, str) and value in TerrainType for value in data["terrains"])
        assert validate_creature_stat_block(data) == []


def test_catalog_columns_and_indexes(fresh_migrated_db):
    async def check():
        conn = await asyncpg.connect(fresh_migrated_db)
        try:
            indexes = await conn.fetch("SELECT indexdef FROM pg_indexes WHERE tablename = 'creatures'")
            definitions = "\n".join(row["indexdef"] for row in indexes)
            for column in ("category", "tier", "name"):
                assert f"({column})" in definitions
            authored = json.loads((ROOT / "content/creatures.json").read_text())
            authored_ids = [row["id"] for row in authored]
            assert len(authored_ids) == len(set(authored_ids))
            await seed_content.seed(conn)
            await conn.execute("UPDATE creatures SET data = data - 'terrains'")
            counts = await seed_content.seed(conn)
            assert counts["creatures"] == len(authored)
            rows = await conn.fetch("SELECT id, data, name, category, tier, level FROM creatures ORDER BY id")
            assert_catalog_rows(rows)
            assert {row["id"] for row in rows} == set(authored_ids)
            assert {row["id"]: json.loads(row["data"])["terrains"] for row in rows} == {
                row["id"]: row["terrains"] for row in authored
            }
            for key, pin in SIGNATURE_PINS.items():
                matches = [row for row in rows if row["id"] == key]
                assert len(matches) == 1
                assert json.loads(matches[0]["data"])["signature_ability"] == pin
                for cue in (None, ""):
                    damaged_signature = {**pin}
                    if cue is None:
                        del damaged_signature["narration_cue"]
                    else:
                        damaged_signature["narration_cue"] = cue
                    payload = json.loads(matches[0]["data"])
                    payload["signature_ability"] = damaged_signature
                    await conn.execute("UPDATE creatures SET data = $2::jsonb WHERE id = $1", key, json.dumps(payload))
                    assert f"{key}: signature_ability.narration_cue: invalid" in await seed_content.validate(conn)
                await conn.execute("UPDATE creatures SET data = $2::jsonb WHERE id = $1", key, matches[0]["data"])
            for row in rows:
                data = json.loads(row["data"])
                assert (row["name"], row["category"], row["tier"], row["level"]) == (
                    data["name"],
                    data["category"],
                    data["tier"],
                    data["level"],
                )
            damaged = json.loads(rows[0]["data"])
            damaged["attacks"][0]["damage"] = 4
            # Both exemplars are tier 1 and level 1, so only distinct values tell those columns apart.
            damaged.update(tier=3, level=11)
            await conn.execute(
                "UPDATE creatures SET data = $2::jsonb WHERE id = $1", rows[0]["id"], json.dumps(damaged)
            )
            derived = await conn.fetchrow("SELECT tier, level FROM creatures WHERE id = $1", rows[0]["id"])
            assert (derived["tier"], derived["level"]) == (3, 11)
            assert f"{rows[0]['id']}: attacks[0].damage: expected string" in await seed_content.validate(conn)
        finally:
            await conn.close()

    asyncio.run(check())


def test_internal_catalog_queries_use_regions_tier_and_named_missing_error(fresh_migrated_db, monkeypatch):
    async def check():
        conn = await asyncpg.connect(fresh_migrated_db)
        try:
            await seed_content.seed(conn)

            async def get_pool():
                return conn

            monkeypatch.setattr(db, "get_pool", get_pool)
            for key, pin in SIGNATURE_PINS.items():
                assert (await query_creature_by_id(key))["signature_ability"] == pin
            assert (await query_creature_by_id("tidecaller_eel"))["terrains"] == ["coast", "wetland"]
            shadeling = await query_creature_by_id("hollow_shadeling")
            assert shadeling["id"] == "hollow_shadeling"
            assert shadeling["regions"] == ["ashmark", "greyvale"]
            with pytest.raises(CreatureNotFoundError, match="no_such"):
                await query_creature_by_id("no_such")
            with pytest.raises(ValueError, match="atlantis"):
                await query_creatures_by_region("atlantis")
        finally:
            await conn.close()

    asyncio.run(check())


@pytest.mark.parametrize("creature_id", list(SIGNATURE_PINS))
def test_signature_survives_real_seed_and_query(migrated_db, monkeypatch, creature_id):
    async def check():
        conn = await asyncpg.connect(migrated_db)
        try:
            raw = await conn.fetchval("SELECT data FROM creatures WHERE id = $1", creature_id)
            assert json.loads(raw)["signature_ability"] == SIGNATURE_PINS[creature_id]

            async def get_pool():
                return conn

            monkeypatch.setattr(db, "get_pool", get_pool)
            assert (await query_creature_by_id(creature_id))["signature_ability"] == SIGNATURE_PINS[creature_id]
        finally:
            await conn.close()

    asyncio.run(check())


@pytest.fixture
def mock_combat_agent_factory():
    return None


@pytest.mark.parametrize(
    "location,levels,region,tier",
    [
        ("greyvale_wilderness_north", (3,), "greyvale", 1),
        ("greyvale_wilderness_north", (3, 7), "greyvale", 2),
        ("sunward_tidal_shore", (3,), "sunward_coast", 1),
        ("sunward_tidal_shore", (7,), "sunward_coast", 2),
    ],
)
async def test_public_creature_queries(reset_db_pool, location, levels, region, tier):
    from acceptance.mawling_harness import MawlingHarness

    h = MawlingHarness()
    try:
        await h.prepare(levels, location=location)
        async with h.pool.acquire() as conn:
            async with conn.transaction():
                shadeling = json.loads(await conn.fetchval("SELECT data FROM creatures WHERE id='hollow_shadeling'"))
                scratch = {**shadeling, "id": "scratch_tier_two", "tier": 2, "regions": ["greyvale"]}
                await conn.execute(
                    "INSERT INTO creatures (id,data) VALUES ($1,$2::jsonb)", scratch["id"], json.dumps(scratch)
                )
                # Route our DB seam to this transaction so the inserted row is visible to commands.
                from unittest.mock import AsyncMock, patch

                with patch("db.get_pool", AsyncMock(return_value=conn)):
                    result = await h.command("query_info", {"kind": "creature"})
                    expected = {
                        r["id"]
                        for r in await conn.fetch(
                            "SELECT id FROM creatures WHERE data->'regions' @> $1::jsonb AND tier=$2",
                            json.dumps([region]),
                            tier,
                        )
                    }
                    assert expected and {r["id"] for r in result} == expected
                    assert ("hollow_shadeling" in expected) == (region == "greyvale" and tier == 1)
                    assert ("scratch_tier_two" in expected) == (region == "greyvale" and tier == 2)
                    explicit = await h.command("query_info", {"kind": "creature", "target_id": "tidecaller_eel"})
                    row = json.loads(await conn.fetchval("SELECT data FROM creatures WHERE id='tidecaller_eel'"))
                    assert explicit["id"] == "tidecaller_eel"
                    for key in (
                        "name",
                        "tier",
                        "category",
                        "level",
                        "hp",
                        "ac",
                        "speed",
                        "attacks",
                        "narration",
                        "audio",
                    ):
                        assert explicit[key] == row[key]
                    error = await h.command("query_info", {"kind": "creature", "target_id": "no_such"}, error=True)
                    assert "no_such" in error
                raise RollbackQuery()
    except RollbackQuery:
        pass
    finally:
        if hasattr(h, "session"):
            await h.close()


class RollbackQuery(Exception):
    pass


@pytest.mark.parametrize("region,exists", [(None, False), (None, True), ("atlantis", True)])
async def test_public_catalog_refuses_unknown_location_or_region(reset_db_pool, region, exists):
    from uuid import uuid4

    from acceptance.mawling_harness import MawlingHarness

    h = MawlingHarness()
    location_id = f"catalog_missing_{uuid4().hex}"
    try:
        await h.prepare(location=location_id)
        if exists:
            await h.pool.execute(
                "INSERT INTO locations (id,data) VALUES ($1,$2::jsonb)",
                location_id,
                json.dumps({"id": location_id, "region": region}),
            )
        error = await h.command("query_info", {"kind": "creature"}, error=True)
        assert ("region" if exists else location_id) in error
        if region:
            assert region in error
    finally:
        await h.close()
        await h.pool.execute("DELETE FROM locations WHERE id=$1", location_id)
