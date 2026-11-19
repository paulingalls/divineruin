import json
from pathlib import Path
from uuid import uuid4

import pytest

import db
import db_content_queries

HEAL_ITEMS = {
    "healing_potion",
    "healing_potion_minor",
    "healing_potion_standard",
    "healing_potion_greater",
    "healing_salve",
    "healing_poultice",
    "restoration_salve",
    "goodberry",
}


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize(
    "effects,index",
    [
        ([{"type": "heal"}], 0),
        ([{"type": "heal", "amount": False}], 0),
        ([{"type": "heal", "amount": 2}], 0),
        ([{"type": "heal", "amount": ""}], 0),
        ([{"type": "heal", "amount": "0d4"}], 0),
        ([{"type": "heal", "amount": "1d4"}, {"type": "heal", "amount": "1d4"}], 1),
    ],
)
async def test_item_reader_rejects_invalid_heals(dev_db_pool, cached, effects, index):
    item_id = f"invalid_heal_{uuid4().hex}"
    data = json.dumps({"id": item_id, "effects": effects})
    if cached:
        await db._cache_set(f"item:{item_id}", data)
        assert await db._cache_get(f"item:{item_id}") == data
    else:
        await dev_db_pool.execute("INSERT INTO items (id, data) VALUES ($1, $2::jsonb)", item_id, data)
    try:
        with pytest.raises(ValueError, match=rf"{item_id}.*effects\[{index}\]"):
            await db_content_queries.get_item(item_id)
    finally:
        await dev_db_pool.execute("DELETE FROM items WHERE id=$1", item_id)
        await (await db.get_redis()).delete(f"item:{item_id}")


async def test_authored_heals_survive_python_item_loading(dev_db_pool):
    path = Path(__file__).resolve().parents[3] / "content" / "items.json"
    rows = {row["id"]: row for row in json.loads(path.read_text()) if any(e["type"] == "heal" for e in row["effects"])}
    assert rows.keys() >= HEAL_ITEMS
    assert next(e["amount"] for e in rows["goodberry"]["effects"] if e["type"] == "heal") == "1d1"
    for item_id, row in rows.items():
        item = await db_content_queries.get_item(item_id)
        assert item is not None
        assert item["effects"] == row["effects"]
