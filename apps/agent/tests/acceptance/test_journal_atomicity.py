"""Journal grant and automatic stage entry roll back with their rewards."""

from copy import deepcopy
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
                assert await arc.quantity("veythar_sealed_artifact", conn=conn) == 1
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
