"""Purification through the public voice command and persisted worker boundary."""

import asyncio
import json
import random
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from acceptance.purification_harness import PurificationHarness, worker_services
from sample_fixtures import published_payloads

import async_worker
import training_rules
from db_inventory_snapshot import get_inventory_snapshot


@pytest.fixture
async def h(reset_db_pool):
    harness = await PurificationHarness().start()
    try:
        yield harness
    finally:
        await harness.close()


async def test_escrow_uses_three_independent_persisted_training_cycles(h, monkeypatch):
    import purification_tools

    original = await h.pool.fetchval("SELECT data FROM training_activity_types WHERE id='skill_practice'")
    config = json.loads(original)
    config.update(
        first_half_min_seconds=101, first_half_max_seconds=199, second_half_min_seconds=201, second_half_max_seconds=299
    )
    monkeypatch.setattr(training_rules, "_activity_types", {})
    now = datetime.fromisoformat("2026-01-01T00:00:00+00:00")
    monkeypatch.setattr(purification_tools, "utc_now", lambda: now)
    rng = random.Random(42)
    expected_rng = random.Random(42)
    seconds = sum(expected_rng.randint(101, 199) + expected_rng.randint(201, 299) for _ in range(3))
    with patch.object(purification_tools.random, "Random", return_value=rng):
        try:
            await h.pool.execute(
                "UPDATE training_activity_types SET data=$1::jsonb WHERE id='skill_practice'", json.dumps(config)
            )
            result = await h.begin()
        finally:
            await h.pool.execute(
                "UPDATE training_activity_types SET data=$1::jsonb WHERE id='skill_practice'", original
            )
    activity = await h.activity(result["activity_id"])
    assert activity["activity_type"] == "purification" and activity["status"] == "in_progress"
    assert "slot" not in activity
    assert activity["parameters"] == {"item_id": "rend_shard", "quantity": 2}
    assert datetime.fromisoformat(activity["resolve_at"]) == now + timedelta(seconds=seconds)
    assert result["resolve_at"] == activity["resolve_at"]
    rows = await h.rows()
    assert [json.loads(r["data"])["quantity"] for r in rows] == [5, 1]
    assert all(json.loads(r["data"])["source"] == "fixture" for r in rows)
    snapshot = await get_inventory_snapshot(h.pid)
    events = [e for e in published_payloads(h.sd.room) if e["type"] == "inventory_updated"]
    assert {k: events[-1][k] for k in snapshot} == snapshot


@pytest.mark.parametrize(
    "item,output,clean", [("rend_shard", "rend_shard", 5), ("salvageable_weapon", "battleaxe_common", 0)]
)
async def test_worker_credits_escrow_once_after_due(reset_db_pool, item, output, clean):
    h = await PurificationHarness().start(item=item, clean=clean)
    try:
        result = await h.begin(3)
        with worker_services():
            await async_worker.resolve_due_activities()
            assert (await h.activity(result["activity_id"]))["status"] == "in_progress"
            assert [(r["item_id"], json.loads(r["data"])["quantity"]) for r in await h.rows()] == (
                [(item, clean)] if clean else []
            )
            await h.due(result["activity_id"])
            await async_worker.resolve_due_activities()
            await async_worker.resolve_due_activities()
        activity = await h.activity(result["activity_id"])
        assert activity["status"] == "resolved"
        assert activity["outcome"]["item_id"] == output
        assert activity["narration_text"] and activity["narration_audio_url"]
        assert activity["decision_options"] == [{"id": "collect", "label": "Acknowledge purification"}]
        stacks = await h.rows()
        assert [(r["item_id"], json.loads(r["data"])["quantity"]) for r in stacks] == [(output, clean + 3)]
    finally:
        await h.close()


@pytest.mark.parametrize(
    "class_,item,held,quantity,message",
    [
        ("warrior", "rend_shard", 3, 2, "Artificer"),
        ("artificer", "rend_shard", 3, 4, "held tainted"),
        ("artificer", "rend_shard", 3, 0, "quantity"),
        ("artificer", "rend_shard", 3, -1, "quantity"),
        ("artificer", "rend_shard", 0, 1, "tainted"),
        ("artificer", "corruption_saturated_stone", 3, 1, "unpurifiable"),
        ("artificer", "rend_shard", 3, "2", "integer"),
    ],
)
async def test_refusal_preserves_inventory(reset_db_pool, class_, item, held, quantity, message):
    h = await PurificationHarness().start(class_=class_, item=item, held=held)
    try:
        before = await get_inventory_snapshot(h.pid)
        rows = await h.rows()
        result = await h.begin(quantity, error=True)
        assert message.lower() in result.lower()
        assert await get_inventory_snapshot(h.pid) == before
        assert await h.rows() == rows
        assert await h.pool.fetchval("SELECT count(*) FROM async_activities WHERE player_id=$1", h.pid) == 0
        assert not [e for e in published_payloads(h.sd.room) if e["type"] == "inventory_updated"]
    finally:
        await h.close()


async def test_two_workers_observe_same_due_row_and_credit_once(h, monkeypatch):
    result = await h.begin()
    await h.due(result["activity_id"])
    real_due = async_worker.db_activity_queries.get_due_activities
    ready = asyncio.Event()
    arrivals = 0

    async def together():
        nonlocal arrivals
        rows = await real_due()
        arrivals += 1
        if arrivals == 2:
            ready.set()
        await asyncio.wait_for(ready.wait(), 5)
        return rows

    monkeypatch.setattr(async_worker.db_activity_queries, "get_due_activities", together)
    with worker_services():
        await asyncio.gather(async_worker.resolve_due_activities(), async_worker.resolve_due_activities())
    assert (await h.activity(result["activity_id"]))["status"] == "resolved"
    assert [json.loads(r["data"])["quantity"] for r in await h.rows()] == [7, 1]
