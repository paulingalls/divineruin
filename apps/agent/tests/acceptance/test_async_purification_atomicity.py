"""One-time fault injection of purification's escrow and terminal transaction."""

import json
from unittest.mock import patch

from acceptance.purification_harness import PurificationHarness, worker_services

import async_worker
import db_mutations
import inventory_allocation


async def test_terminal_cas_loss_cannot_credit(reset_db_pool):
    h = await PurificationHarness().start()
    try:
        result = await h.begin()
        activity_id = result["activity_id"]
        await h.due(activity_id)
        original = await h.rows()
        with worker_services():

            async def lose_claim(*args):
                await h.pool.execute(
                    "UPDATE async_activities SET data=jsonb_set(data,'{status}','\"in_progress\"') WHERE id=$1",
                    activity_id,
                )

            with patch.object(async_worker, "synthesize_segments", lose_claim):
                await async_worker.resolve_due_activities()
            assert await h.rows() == original
            assert (await h.activity(activity_id))["status"] == "in_progress"
            await async_worker.resolve_due_activities()
        assert [json.loads(r["data"])["quantity"] for r in await h.rows()] == [7, 1]
        assert (await h.activity(activity_id))["status"] == "resolved"
    finally:
        await h.close()


async def test_credit_failure_rolls_back_credit_and_terminal_status(reset_db_pool):
    h = await PurificationHarness().start()
    try:
        result = await h.begin()
        activity_id = result["activity_id"]
        await h.due(activity_id)
        original = await h.rows()
        credit = inventory_allocation.credit_clean

        async def write_then_fail(*args):
            await credit(*args)
            raise RuntimeError("credit fault after real write")

        with worker_services():
            with patch.object(inventory_allocation, "credit_clean", write_then_fail):
                await async_worker.resolve_due_activities()
            assert await h.rows() == original
            activity = await h.activity(activity_id)
            assert activity["status"] == "in_progress"
            assert activity["parameters"] == {"item_id": "rend_shard", "quantity": 2}
            await async_worker.resolve_due_activities()
        assert [json.loads(r["data"])["quantity"] for r in await h.rows()] == [7, 1]
        assert (await h.activity(activity_id))["status"] == "resolved"
    finally:
        await h.close()


async def test_command_insert_failure_rolls_back_escrow(reset_db_pool):
    h = await PurificationHarness().start()
    try:
        original = await h.rows()
        create = db_mutations.create_async_activity

        async def insert_then_fail(*args, **kwargs):
            await create(*args, **kwargs)
            raise ConnectionError("activity insert fault")

        with patch.object(db_mutations, "create_async_activity", insert_then_fail):
            error = await h.begin(error=True)
        assert "trouble accessing" in error
        assert await h.rows() == original
        assert await h.pool.fetchval("SELECT count(*) FROM async_activities WHERE player_id=$1", h.pid) == 0
        assert (await h.begin())["activity_id"]
    finally:
        await h.close()
