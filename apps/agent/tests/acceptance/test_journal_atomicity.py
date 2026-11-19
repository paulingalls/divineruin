"""Journal grant and automatic stage entry roll back with their rewards."""

import asyncio
from copy import copy, deepcopy
from unittest.mock import patch

import pytest
from acceptance.greyvale_arc_walk_harness import QUEST
from acceptance.journal_walk import ITEM, JournalWalk
from livekit.agents.llm import ToolError

import db_mutations
import db_queries
import event_types as E


@pytest.mark.parametrize("entry", [False, True])
def test_journal_rollback_and_retry(harness, entry):
    async def check():
        arc = await JournalWalk().start(harness, 2 if entry else 3)
        # The token commits independently of the journal reward transaction.
        await arc.discover(target="loose rubble")
        if entry:
            await arc.discover()
        before = await arc.durable()
        metrics = (arc.sd.session_xp_earned, list(arc.sd.session_quests_progressed))
        member_metrics = deepcopy(arc.sd.player_summary_metrics)
        items_found = list(arc.sd.session_items_found)
        corruption = arc.sd.corruption_level
        attempts = set(arc.sd.attempted_discoveries)
        arc.events.clear()
        original = db_mutations.set_player_quest
        reached = []

        async def fail_after_marker(player, quest, data, *, conn=None):
            await original(player, quest, data, conn=conn)
            if quest == QUEST and data["current_stage"] == 4:
                assert await arc.quantity(conn=conn) == 1
                row = await db_queries.get_player(arc.player, conn=conn)
                assert row is not None
                assert row["flags"][ITEM + ".discovered"] is True
                assert row["xp"] == (350 if entry else 200)
                assert await arc.quantity("veythar_sealed_artifact", conn=conn) == 0
                reached.append(True)
                raise ToolError("injected journal rollback")

        async def run(error=False):
            if entry:
                return await arc.command("update_quest", {"quest_id": QUEST, "new_stage_id": 3}, error=error)
            return await arc.discover(error=error)

        with patch.object(db_mutations, "set_player_quest", side_effect=fail_after_marker):
            assert "injected journal rollback" in await run(error=True)
        assert reached == [True]
        assert await arc.durable() == before
        assert (arc.sd.session_xp_earned, arc.sd.session_quests_progressed) == metrics
        assert arc.sd.player_summary_metrics == member_metrics
        assert arc.sd.session_items_found == items_found
        assert arc.sd.corruption_level == corruption
        assert arc.sd.attempted_discoveries == attempts
        assert not [e for e in arc.events if e["type"] != E.DICE_ROLL]
        result = await run()
        assert await arc.marker() == 4
        if not entry:
            await arc.rewarded(result)

    harness.run_sync(check())


def test_concurrent_discoveries_grant_and_pay_once(harness):
    async def check():
        from acceptance.voice_condition_harness import ScenarioModel
        from livekit.agents import Agent, AgentSession

        import check_discovery
        from exploration_agent import EXPLORATION_TOOLS
        from session_data import SessionData

        first = await JournalWalk().start(harness)
        second = copy(first)
        second.sd = SessionData(player_id=first.player, location_id=first.sd.location_id, room=first.sd.room)
        second.model = ScenarioModel([])
        second.session = AgentSession(llm=second.model, userdata=second.sd)
        await second.session.start(
            Agent(instructions="Execute the command.", tools=[t for t in EXPLORATION_TOOLS if t.__name__ == "check"])
        )
        harness.stack.callback(lambda: harness.run_sync(second.session.aclose()))
        original = check_discovery.lock_discovery_rows
        selected = []
        ready = asyncio.Event()

        async def rendezvous(session, **kwargs):
            selected.append(session)
            if len(selected) == 2:
                ready.set()
            await asyncio.wait_for(ready.wait(), 5)
            return await original(session, **kwargs)

        with patch.object(check_discovery, "lock_discovery_rows", side_effect=rendezvous):
            await asyncio.gather(first.discover(), second.discover())
        assert selected == [first.sd, second.sd] or selected == [second.sd, first.sd]
        assert await first.quantity() == 1
        assert await first.marker() == 4
        player = await db_queries.get_player(first.player)
        assert player is not None and player["xp"] == 200
        assert len([e for e in first.events if e["type"] == E.QUEST_UPDATED]) == 1

    harness.run_sync(check())
