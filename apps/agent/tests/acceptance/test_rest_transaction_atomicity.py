"""Fault injection and a concurrent writer for the locked atomic rest transaction."""

import asyncio
from unittest.mock import patch

from acceptance.rest_walk import RestWalk

import db_mutations
import db_mutations_conditions


def test_second_member_failure_rolls_back_every_member(harness):
    async def check():
        walk = await RestWalk().setup(harness)
        original = db_mutations.update_player_hp
        calls = 0

        async def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("injected second-member write failure")
            await original(*args, **kwargs)

        with patch.object(db_mutations, "update_player_hp", fail_second):
            receipt = await walk.command("long")
        assert receipt.is_error
        assert calls == 2
        assert await walk.rows() == walk.before
        assert all(walk.sd.member_state(pid).resonance.current == 7 for pid in walk.ids)
        assert not walk.events

    harness.run_sync(check())


def test_rest_waits_for_member_row_and_uses_committed_pool(harness):
    async def check():
        walk = await RestWalk().setup(harness)
        async with walk.pool.acquire() as writer:
            async with writer.transaction():
                await writer.execute(
                    "UPDATE players SET data=jsonb_set(data,'{focus,current}','10') WHERE player_id=$1",
                    walk.ids[1],
                )
                writer_pid = await writer.fetchval("SELECT pg_backend_pid()")
                task = asyncio.create_task(walk.command("short"))
                try:
                    async with asyncio.timeout(5):
                        while not await walk.pool.fetchval(
                            "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE $1=ANY(pg_blocking_pids(pid)))",
                            writer_pid,
                        ):
                            if task.done():
                                await task
                                raise AssertionError("rest completed before the locked member committed")
                    # The writer commits only after PostgreSQL observes rest waiting on its lock.
                except BaseException:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    raise
        receipt = await asyncio.wait_for(task, 5)
        assert not receipt.is_error, receipt.output
        assert (await walk.rows())[walk.ids[1]]["focus"]["current"] == 10

    harness.run_sync(check())


def test_condition_write_failure_rolls_back_long_rest(harness):
    async def check() -> None:
        walk = await RestWalk().setup(harness)
        for pid in walk.ids[:2]:
            await db_mutations_conditions.save_player_conditions(pid, [{"type": "hollowed", "stage": 1}])
        before = await walk.rows()
        original = db_mutations_conditions.save_player_conditions
        calls = 0

        async def fail_second(*args, **kwargs) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("injected second-member condition write failure")
            await original(*args, **kwargs)

        with patch.object(db_mutations_conditions, "save_player_conditions", fail_second):
            receipt = await walk.command("long")
        assert receipt.is_error
        assert calls == 2
        assert await walk.rows() == before
        assert not walk.events

    harness.run_sync(check())
