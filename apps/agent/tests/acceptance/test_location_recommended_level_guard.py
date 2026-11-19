import json
from contextlib import nullcontext
from unittest.mock import patch
from uuid import uuid4

import pytest

import db
from db_content_queries import get_all_locations, get_location

FRONT = "ashmark_corrupted_front"
STILL = "ashmark_still"
NORTH = "greyvale_wilderness_north"


async def test_optional_recommended_levels_on_cold_and_cached_reads(reset_db_pool, monkeypatch):
    prefix = f"recommendation_{uuid4().hex}:"
    monkeypatch.setenv("CONTENT_CACHE_PREFIX", prefix)
    expected = {FRONT: 14, STILL: 18, NORTH: None}
    keys = ["locations:all", *(f"location:{location}" for location in expected)]
    try:
        for cached in (False, True):
            for key in keys:
                assert (await db._cache_get(key) is not None) is cached
            with (
                patch.object(db, "get_pool", side_effect=AssertionError("expected cache hit"))
                if cached
                else nullcontext()
            ):
                catalog = await get_all_locations()
                for location, level in expected.items():
                    row = await get_location(location)
                    assert row is not None and row == catalog[location]
                    if level is None:
                        assert "recommended_level" not in row
                    else:
                        assert row["recommended_level"] == level
    finally:
        await (await db.get_redis()).delete(*(prefix + key for key in keys))


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("read_all", [False, True])
async def test_rejects_corrupt_recommendations_on_each_read_path(reset_db_pool, monkeypatch, cached, read_all):
    prefix = f"recommendation_{uuid4().hex}:"
    monkeypatch.setenv("CONTENT_CACHE_PREFIX", prefix)
    pool = await db.get_pool()
    key = "locations:all" if read_all else f"location:{FRONT}"
    values = (14.5, True, "14", None) if cached and not read_all else (14.5,)
    async with pool.acquire() as conn, conn.transaction():
        original = json.loads(await conn.fetchval("SELECT data FROM locations WHERE id=$1", FRONT))
        try:
            for value in values:
                row = dict(original, recommended_level=value)
                if cached:
                    await db._cache_set(key, json.dumps({FRONT: row} if read_all else row))
                    assert await db._cache_get(key) is not None
                else:
                    await conn.execute("UPDATE locations SET data=$2::jsonb WHERE id=$1", FRONT, json.dumps(row))
                pool_result = (
                    patch.object(db, "get_pool", side_effect=AssertionError("expected cache hit"))
                    if cached
                    else patch.object(db, "get_pool", return_value=conn)
                )
                with pool_result:
                    with pytest.raises(ValueError, match=rf"{FRONT}.*recommended_level"):
                        await (get_all_locations() if read_all else get_location(FRONT))
        finally:
            if not cached:
                await conn.execute("UPDATE locations SET data=$2::jsonb WHERE id=$1", FRONT, json.dumps(original))
            await (await db.get_redis()).delete(prefix + key)
