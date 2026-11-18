"""One durable spend across independent sessions; failures roll back."""

import asyncio
import copy
from unittest.mock import patch

from livekit.agents.llm import ToolError
from patron_ability_walk import AbilityWalk

import patron_gift_tools

LIBRARY = "veythar_lorekeepers_library"


async def test_independent_sessions_wait_for_player_lock_and_spend_once(dev_db_pool):
    async with AbilityWalk(dev_db_pool) as first:
        second = copy.copy(first)
        await second.connect()
        assert first.sd.combat_state_lock is not second.sd.combat_state_lock
        tasks = []
        try:
            async with dev_db_pool.acquire() as writer:
                async with writer.transaction():
                    await writer.fetchrow("SELECT * FROM players WHERE player_id=$1 FOR UPDATE", first.player)
                    pid = await writer.fetchval("SELECT pg_backend_pid()")
                    tasks = [asyncio.create_task(w.use(LIBRARY, error=None)) for w in (first, second)]
                    async with asyncio.timeout(5):
                        while (
                            await dev_db_pool.fetchval(
                                """WITH RECURSIVE blocked(pid) AS (
                            SELECT pid FROM pg_stat_activity WHERE $1=ANY(pg_blocking_pids(pid))
                            UNION SELECT a.pid FROM pg_stat_activity a JOIN blocked b
                            ON b.pid=ANY(pg_blocking_pids(a.pid))) SELECT count(*) FROM blocked""",
                                pid,
                            )
                            < 2
                        ):
                            assert not any(t.done() for t in tasks)
                            await asyncio.sleep(0.01)
            results = await asyncio.wait_for(asyncio.gather(*tasks), 10)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        assert sum(isinstance(r, dict) and "effect" in r for r in results) == 1
        assert sum(isinstance(r, str) and "spent" in r for r in results) == 1
        assert (await first.row())["patron_gifts"][LIBRARY] == {"spent": True}


async def test_failure_after_write_rolls_back_spend(dev_db_pool):
    async with AbilityWalk(dev_db_pool) as w:
        before = await w.row()
        write = patron_gift_tools.write_state
        reached = []

        async def fail_after_write(*args, **kwargs):
            await write(*args, **kwargs)
            reached.append(True)
            raise ToolError("injected after spend")

        with patch.object(patron_gift_tools, "write_state", fail_after_write):
            assert "injected after spend" in await w.use(LIBRARY, error=True)
        assert reached == [True] and await w.row() == before
        await w.use(LIBRARY)
        assert (await w.row())["patron_gifts"][LIBRARY] == {"spent": True}


async def test_departure_during_player_read_cannot_spend(dev_db_pool, monkeypatch):
    import db_queries

    async with AbilityWalk(dev_db_pool) as w:
        before = await w.row()
        revoked = False
        read = db_queries.get_player

        async def revoke_after_read(*args, **kwargs):
            nonlocal revoked
            row = await read(*args, **kwargs)
            revoked = True
            return row

        def validate(*_):
            if revoked:
                raise ToolError("actor revoked")

        w.validator = validate
        with monkeypatch.context() as m:
            m.setattr(db_queries, "get_player", revoke_after_read)
            assert "actor revoked" in await w.use(LIBRARY, error=True)
        assert await w.row() == before
