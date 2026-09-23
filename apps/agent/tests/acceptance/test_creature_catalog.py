import asyncio
import importlib
import json
import sys
from pathlib import Path

import asyncpg
import pytest

import db
from creature_catalog import CreatureNotFoundError, query_creature_by_id, query_creatures_by_region
from creature_schema import validate_creature_stat_block

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))
seed_content = importlib.import_module("seed_content")


def assert_catalog_rows(rows):
    assert rows
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids))
    assert {"hollow_shadeling", "hollow_hollowmoth"} <= set(ids)
    for row in rows:
        assert validate_creature_stat_block(json.loads(row["data"])) == []


def test_catalog_floor_accepts_more_rows_and_rejects_missing_exemplars():
    creatures = json.loads((ROOT / "content/creatures.json").read_text())
    rows = [{"id": block["id"], "data": json.dumps(block)} for block in creatures]
    extra = {**creatures[0], "id": "scratch_third_creature"}
    assert_catalog_rows([*rows, {"id": extra["id"], "data": json.dumps(extra)}])
    with pytest.raises(AssertionError):
        assert_catalog_rows([])
    for row in rows:
        with pytest.raises(AssertionError):
            assert_catalog_rows([other for other in rows if other is not row])


def test_catalog_columns_and_indexes(fresh_migrated_db):
    async def check():
        conn = await asyncpg.connect(fresh_migrated_db)
        try:
            indexes = await conn.fetch("SELECT indexdef FROM pg_indexes WHERE tablename = 'creatures'")
            definitions = "\n".join(row["indexdef"] for row in indexes)
            for column in ("category", "tier", "name"):
                assert f"({column})" in definitions
            await seed_content.seed(conn)
            rows = await conn.fetch("SELECT id, data, name, category, tier, level FROM creatures ORDER BY id")
            assert_catalog_rows(rows)
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
            shadeling = await query_creature_by_id("hollow_shadeling")
            assert shadeling["id"] == "hollow_shadeling"
            assert shadeling["regions"] == ["ashmark", "greyvale"]
            with pytest.raises(CreatureNotFoundError, match="no_such"):
                await query_creature_by_id("no_such")
            with pytest.raises(ValueError, match="atlantis"):
                await query_creatures_by_region("atlantis")
            ashmark = await query_creatures_by_region("ashmark")
            assert {row["id"] for row in ashmark} >= {"hollow_shadeling", "hollow_hollowmoth"}
            ashmark_tier_two = {row["id"] for row in await query_creatures_by_region("ashmark", tier=2)}
            assert not ashmark_tier_two & {"hollow_shadeling", "hollow_hollowmoth"}
            greyvale = await query_creatures_by_region("greyvale")
            assert {row["id"] for row in greyvale} >= {"hollow_shadeling", "hollow_hollowmoth"}
            scratch = {**shadeling, "id": "scratch_tier_two", "tier": 2, "regions": ["greyvale"]}
            await conn.execute(
                "INSERT INTO creatures (id, data) VALUES ($1, $2::jsonb)", scratch["id"], json.dumps(scratch)
            )
            greyvale_tier_two = {row["id"] for row in await query_creatures_by_region("greyvale", tier=2)}
            assert "scratch_tier_two" in greyvale_tier_two
            assert not greyvale_tier_two & {"hollow_shadeling", "hollow_hollowmoth"}
        finally:
            await conn.close()

    asyncio.run(check())
