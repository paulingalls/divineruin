import os
import uuid

import pytest
import redis.asyncio as aioredis

import db


@pytest.mark.asyncio
async def test_real_valkey_get_reads_value():
    client = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    previous = db._redis
    db._redis = client
    key = f"test:real-read:{uuid.uuid4()}"
    try:
        await client.set(key, "ordinary-value", ex=30)
        assert await db._cache_get(key) == "ordinary-value"
        await client.delete(key)
    finally:
        db._redis = previous
        await client.aclose()
