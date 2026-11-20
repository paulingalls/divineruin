"""Community Shield rolls back as a unit and rechecks eligibility after locking."""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import asyncpg
import pytest
from _aelora_shield_fixtures import SHIELD, SPENT, checkpoint, shield_setup, snapshot
from _unbound_path_fixtures import world as world
from livekit.agents.llm import ToolError

import db_mutations
import db_queries


async def test_failure_after_checkpoint_rolls_back_grant_and_spend(world: SimpleNamespace) -> None:
    async with shield_setup(world, combat=True) as call:
        actor, ally = world.ids
        session = world.ctx.userdata
        original = session.combat_state
        before = await snapshot(world)
        save = db_mutations.save_combat_state

        async def fail_after_save(combat_id: str, state: dict, *, conn: asyncpg.Connection) -> None:
            await save(combat_id, state, conn=conn)
            follower_row = await db_queries.get_player(actor, conn=conn)
            ally_row = await db_queries.get_player(ally, conn=conn)
            assert follower_row is not None and follower_row["patron_gifts"][SHIELD] == SPENT
            assert ally_row is not None and ally_row["temp_hp"] == 9
            saved = await checkpoint(world, conn=conn)
            assert saved is not None
            assert next(p["temp_hp"] for p in saved["participants"] if p["id"] == ally) == 9
            raise ToolError("injected after Community Shield checkpoint")

        with (
            patch.object(db_mutations, "save_combat_state", fail_after_save),
            pytest.raises(ToolError, match="injected after Community Shield checkpoint"),
        ):
            await asyncio.wait_for(call("activate", id=SHIELD, target_id=ally), timeout=5)
        assert session.combat_state is original
        assert await snapshot(world) == before
        assert (await call("activate", id=SHIELD, target_id=ally))["temp_hp"] == 9


@pytest.mark.parametrize("case", ["larger-pool", "departure"])
async def test_waiting_shield_rechecks_target(world: SimpleNamespace, case: str) -> None:
    async with shield_setup(world, combat=True) as call:
        _, ally = world.ids
        before = await snapshot(world)
        task = None
        try:
            async with world.pool.acquire() as writer, writer.transaction():
                await writer.fetchval("SELECT player_id FROM players WHERE player_id=$1 FOR UPDATE", ally)
                writer_pid = await writer.fetchval("SELECT pg_backend_pid()")
                task = asyncio.create_task(call("activate", id=SHIELD, target_id=ally))
                async with asyncio.timeout(5):
                    while not await world.pool.fetchval(
                        "SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE $1=ANY(pg_blocking_pids(pid)))",
                        writer_pid,
                    ):
                        if task.done():
                            await task
                            pytest.fail("Community Shield completed before the target row unlocked")
                if case == "larger-pool":
                    await db_mutations.update_player_temp_hp(ally, 12, conn=writer)
                    assert before[0][1] is not None
                    before[0][1]["temp_hp"] = 12
                else:
                    world.ctx.userdata.multiplayer_owner.lifecycle.mark_departed(ally)
            reason = "would not increase" if case == "larger-pool" else "present party player"
            with pytest.raises(ToolError, match=reason):
                await asyncio.wait_for(task, timeout=5)
        finally:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        assert await snapshot(world) == before
