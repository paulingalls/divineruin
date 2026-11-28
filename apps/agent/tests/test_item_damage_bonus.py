import json
from typing import cast
from uuid import uuid4

import asyncpg
import pytest
from test_sale_pricing import ROOT, authored

import db
from db_content_queries import get_item

CASES = json.loads((ROOT / "packages/shared/fixtures/item-damage-bonus-cases.json").read_text())
ITEMS = {item["id"]: item for item in authored("items.json")}


@pytest.mark.parametrize("source", ("postgres", "valkey"))
@pytest.mark.parametrize(
    ("valid", "case"),
    [pytest.param(group == "valid", case, id=case["id"]) for group, cases in CASES.items() for case in cases],
)
async def test_item_damage_bonus_read(
    dev_db_pool: asyncpg.Pool, monkeypatch: pytest.MonkeyPatch, source: str, valid: bool, case: dict
) -> None:
    prefix = f"item_damage_bonus:{uuid4().hex}:"
    monkeypatch.setenv("CONTENT_CACHE_PREFIX", prefix)
    item_id = f"damage_bonus_{case['id']}_{uuid4().hex}"
    key = f"item:{item_id}"
    row = ITEMS[case["base"]] | {"id": item_id} | {k: v for k, v in case.items() if k == "damage_bonus"}
    raw = json.dumps(row)
    redis = await db.get_redis()
    try:
        async with dev_db_pool.acquire() as connection:
            conn = cast(asyncpg.Connection, connection)
            transaction = conn.transaction()
            await transaction.start()
            try:
                if source == "valkey":
                    await db._cache_set(key, raw)
                    assert await db._cache_get(key) == raw
                else:
                    await conn.execute("INSERT INTO items (id, data) VALUES ($1, $2::jsonb)", item_id, raw)
                if valid:
                    assert await get_item(item_id, conn=conn) == row
                else:
                    with pytest.raises(ValueError, match=rf"{item_id}.*damage_bonus"):
                        await get_item(item_id, conn=conn)
                    if source == "postgres":
                        assert await db._cache_get(key) is None
            finally:
                await transaction.rollback()
    finally:
        await redis.delete(prefix + key)
