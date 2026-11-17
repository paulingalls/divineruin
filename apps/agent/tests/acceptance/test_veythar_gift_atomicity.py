"""Independent sessions contend on PostgreSQL; failed rerolls release no effects."""

import asyncio
import copy
from unittest.mock import patch

from acceptance._capstone_helpers import _d20
from acceptance.greyvale_arc_walk_harness import QUEST
from acceptance.journal_walk import ITEM
from acceptance.veythar_walk import GIFT, GiftWalk
from livekit.agents.llm import ToolError

import db_mutations
import db_queries
import event_types as E


def test_two_sessions_spend_one_pending_discovery(harness):
    async def scenario():
        first = await GiftWalk().start(harness)
        await first.search()
        second = copy.copy(first)
        del second.session
        second.events = []
        await second.connect(harness)
        assert first.sd.combat_state_lock is not second.sd.combat_state_lock
        first.events.clear()
        tasks = []
        with patch("check_resolution.dice_roll", return_value=_d20(20)) as rolls:
            try:
                async with first.pool.acquire() as writer:
                    async with writer.transaction():
                        await writer.fetchrow("SELECT * FROM players WHERE player_id=$1 FOR UPDATE", first.player)
                        pid = await writer.fetchval("SELECT pg_backend_pid()")
                        tasks = [
                            asyncio.create_task(w.command("activate", {"id": GIFT}, error=None))
                            for w in (first, second)
                        ]
                        # Inspect PostgreSQL's lock graph, including the second waiter's quest lock.
                        async with asyncio.timeout(5):
                            while (
                                await first.pool.fetchval(
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
                        assert rolls.call_count == 0
                results = await asyncio.wait_for(asyncio.gather(*tasks), 10)
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        receipts = [list(w.model.receipts.values())[-1] for w in (first, second)]
        assert sum(r.is_error for r in receipts) == 1, results
        assert "spent" in next(r.output for r in receipts if r.is_error)
        assert rolls.call_count == 1
        assert await first.quantity() == 1 and await first.marker() == 4
        assert await first.state() == {"spent": True, "pending": None}
        events = first.events + second.events
        assert sum(e["type"] == E.HIDDEN_REVEALED for e in events) == 1
        assert sum(e["type"] == E.DICE_ROLL for e in events) == 1

    harness.run_sync(scenario())


def test_discovery_spend_rewards_and_session_effects_roll_back(harness):
    async def scenario():
        walk = await GiftWalk().start(harness)
        await walk.search()
        before = await walk.durable()
        metrics = copy.deepcopy(
            (
                walk.sd.session_xp_earned,
                walk.sd.session_quests_progressed,
                walk.sd.player_summary_metrics,
                walk.sd.session_items_found,
                walk.sd.recent_events,
            )
        )
        attempts = set(walk.sd.attempted_discoveries)
        combat = walk.sd.combat_state
        original = db_mutations.set_player_quest
        reached = []

        async def fail_after_rewards(player, quest, data, *, conn=None):
            await original(player, quest, data, conn=conn)
            if quest == QUEST and data["current_stage"] == 4:
                row = await db_queries.get_player(player, conn=conn)
                assert row is not None
                assert row["patron_gifts"][GIFT] == {"spent": True, "pending": None}
                assert row["flags"][ITEM + ".discovered"] and row["xp"] == 200
                assert await walk.quantity(conn=conn) == 1
                reached.append(True)
                raise ToolError("injected gift rollback")

        walk.events.clear()
        with patch.object(db_mutations, "set_player_quest", fail_after_rewards):
            # This error occurs after the die, unlike a refusal before rolling.
            with patch("check_resolution.dice_roll", return_value=_d20(20)) as rolls:
                result = await walk.command("activate", {"id": GIFT}, error=True)
            assert "injected gift rollback" in result and rolls.call_count == 1
        assert reached == [True]
        assert await walk.durable() == before
        assert (
            walk.sd.session_xp_earned,
            walk.sd.session_quests_progressed,
            walk.sd.player_summary_metrics,
            walk.sd.session_items_found,
            walk.sd.recent_events,
        ) == metrics
        assert walk.sd.combat_state is combat and walk.sd.attempted_discoveries == attempts
        assert walk.events == []
        await walk.rewarded(await walk.use())

    harness.run_sync(scenario())
