"""Restoration Surge's transaction and locked condition read."""

import asyncio
from unittest.mock import patch

import pytest
from _unbound_path_fixtures import world as world
from livekit.agents.llm import ToolError
from test_patron_engine_orenthel import SPENT, SURGE, afflicted, checkpoint, snapshot, surge_setup, survivors

import db_queries
import patron_gift_tools
from db_mutations_conditions import save_player_conditions


async def test_failure_after_spend_rolls_back_player_and_checkpoint(world):
    remaining = survivors("poisoned")
    async with surge_setup(world, stored=[afflicted("poisoned"), *remaining], combat=True) as call:
        actor, target = world.ids
        session = world.ctx.userdata
        original = session.combat_state
        before = await snapshot(world)
        write = patron_gift_tools.write_state
        reached = False

        async def fail_after_spend(player_id, state, *, gift_id, conn):
            nonlocal reached
            await write(player_id, state, gift_id=gift_id, conn=conn)
            follower = await db_queries.get_player(actor, conn=conn)
            ally = await db_queries.get_player(target, conn=conn)
            assert follower is not None and ally is not None
            assert follower["patron_gifts"][SURGE] == SPENT
            assert ally["conditions"] == remaining
            saved = await checkpoint(world, conn=conn)
            assert saved is not None
            assert next(p["conditions"] for p in saved["participants"] if p["id"] == target) == remaining
            reached = True
            raise ToolError("injected after Restoration Surge spend")

        args = {"id": SURGE, "target_id": target, "condition": "poisoned"}
        with (
            patch.object(patron_gift_tools, "write_state", fail_after_spend),
            pytest.raises(ToolError, match="injected after Restoration Surge spend"),
        ):
            await asyncio.wait_for(call("activate", **args), timeout=5)
        assert reached
        assert session.combat_state is original
        assert await snapshot(world) == before
        assert (await call("activate", **args))["condition_removed"] == "poisoned"


async def test_waiting_surge_refuses_committed_stage_two(world):
    async with surge_setup(world, stored=[afflicted("hollowed")], combat=True) as call:
        _, target = world.ids
        before = await snapshot(world)
        task = None
        try:
            async with world.pool.acquire() as writer, writer.transaction():
                await writer.fetchval("SELECT player_id FROM players WHERE player_id=$1 FOR UPDATE", target)
                writer_pid = await writer.fetchval("SELECT pg_backend_pid()")
                task = asyncio.create_task(call("activate", id=SURGE, target_id=target, condition="hollowed"))
                async with asyncio.timeout(5):
                    while not await world.pool.fetchval(
                        "SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE $1=ANY(pg_blocking_pids(pid)))",
                        writer_pid,
                    ):
                        if task.done():
                            await task
                            pytest.fail("Restoration Surge completed before the target row unlocked")
                stage_two = [afflicted("hollowed", 2)]
                await save_player_conditions(target, stage_two, conn=writer)
            with pytest.raises(ToolError, match="stage 1 Hollowed"):
                await asyncio.wait_for(task, timeout=5)
        finally:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

        before[0][1]["conditions"] = stage_two
        assert await snapshot(world) == before
