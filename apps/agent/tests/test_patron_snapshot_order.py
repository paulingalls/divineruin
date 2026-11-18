"""A delayed initialization identifies the committed patron state it captured."""

import asyncio
import json
from typing import cast
from unittest.mock import MagicMock, patch

from patron_ability_walk import AbilityWalk

import db_queries
from exploration_agent import ExplorationAgent


async def test_spend_overtakes_initialization_without_losing_its_revision(dev_db_pool):
    async with AbilityWalk(dev_db_pool) as w:
        paused, release = asyncio.Event(), asyncio.Event()
        inventory = db_queries.get_inventory_snapshot
        events = []

        async def delayed(pid):
            paused.set()
            await release.wait()
            return await inventory(pid)

        async def sent(data, **kwargs):
            events.append(json.loads(data))

        cast(MagicMock, w.sd.room).local_participant.publish_data.side_effect = sent
        with patch.object(db_queries, "get_inventory_snapshot", delayed):
            initialization = asyncio.create_task(ExplorationAgent()._publish_session_init(w.sd))
            try:
                await asyncio.wait_for(paused.wait(), timeout=5)
                await w.use("veythar_lorekeepers_library")
            finally:
                release.set()
                await initialization
        update, initial = events
        assert update["type"] == "patron_abilities_updated" and update["abilities"][1]["spent"]
        assert initial["type"] == "session_init" and not initial["abilities"][1]["spent"]
        assert update["patron_revision"] > initial["patron_revision"]
        after = update["patron_revision"]
        await w.command("rest", {"rest_type": "long"})
        assert events[-1]["patron_revision"] > after


async def test_patron_revision_rolls_back_with_state(dev_db_pool):
    import pytest

    import db
    from progression_tools import _award_divine_favor_core

    async with AbilityWalk(dev_db_pool) as w:
        revision = (await w.row())["patron_revision"]
        with pytest.raises(RuntimeError, match="rollback"):
            async with db.transaction() as conn:
                await db_queries.get_player(w.player, conn=conn, for_update=True)
                await _award_divine_favor_core(w.player, 2, "served", conn=conn, pending_events=[])
                changed = await db_queries.get_player(w.player, conn=conn)
                assert changed is not None and changed["patron_revision"] > revision
                raise RuntimeError("rollback")
        assert (await w.row())["patron_revision"] == revision
        async with db.transaction() as conn:
            await db_queries.get_player(w.player, conn=conn, for_update=True)
            await _award_divine_favor_core(w.player, 2, "served", conn=conn, pending_events=[])
        assert (await w.row())["patron_revision"] > revision
