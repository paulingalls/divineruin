"""Production reseeding retires content caches while preserving live state."""

import asyncio
import json
import os
import shutil
import uuid

import redis.asyncio as aioredis
from acceptance.test_creature_catalog import ROOT, seed_content

import db
from db_content_queries import get_location


def test_production_seed_retires_cached_content(fresh_migrated_db, tmp_path, monkeypatch):
    prefix = "seed-cache-" + uuid.uuid4().hex + ":"
    location_id = "seed_cache_" + uuid.uuid4().hex
    monkeypatch.setenv("DATABASE_URL", fresh_migrated_db)
    monkeypatch.setenv("SEED_PRODUCTION", "1")
    monkeypatch.setenv("CONTENT_CACHE_PREFIX", prefix)
    monkeypatch.setattr(seed_content, "CONTENT_DIR", tmp_path / "content")
    shutil.copytree(ROOT / "content", tmp_path / "content")
    path = tmp_path / "content/locations.json"
    locations = json.loads(path.read_text())
    location = dict(locations[0], id=location_id, description="Before deployment")
    locations.append(location)
    path.write_text(json.dumps(locations))

    async def check():
        client = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
        try:
            await seed_content.main()
            cached = await get_location(location_id)
            assert cached is not None and cached["description"] == "Before deployment"
            await db.close_all()
            await client.set(prefix + "session:keep", "live session", ex=60)
            await client.set(prefix + "player:keep", "live player", ex=60)
            # Aggregate content keys must retire along with per-row keys.
            await client.set(prefix + "locations:all", "old aggregate", ex=60)
            location["description"] = "After deployment"
            path.write_text(json.dumps(locations))
            await seed_content.main()
            refreshed = await get_location(location_id)
            assert refreshed is not None and refreshed["description"] == "After deployment"
            assert await client.get(prefix + "locations:all") is None
            assert await client.get(prefix + "session:keep") == "live session"
            assert await client.get(prefix + "player:keep") == "live player"
        finally:
            await db.close_all()
            async for key in client.scan_iter(match=prefix + "*"):
                await client.delete(key)
            await client.delete("location:" + location_id)
            await client.aclose()

    asyncio.run(check())
