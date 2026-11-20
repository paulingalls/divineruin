import asyncio
from unittest.mock import patch

import pytest
from _patron_gateway_fixtures import GIFT, MARKET, MILL, charm, cross, party_rows, prepare, snapshot
from _unbound_path_fixtures import world as world
from livekit.agents.llm import ToolError

import db_mutations_resonance
import db_queries


async def test_gateway_rolls_back_spend_party_arrival_and_resonance(world):
    agent = await prepare(world)
    follower = world.ids[1]
    before = await snapshot(world, agent)
    revisions = [await db_queries.get_player_at_patron_revision(pid) for pid in world.ids]
    update = db_mutations_resonance.update_player_resonance

    async def fail_after_update(player_id, current, *, conn):
        assert player_id == follower and conn.is_in_transaction()
        await update(player_id, current, conn=conn)
        rows = await party_rows(world, conn=conn)
        assert {row["location_id"] for row in rows.values()} == {MILL}
        assert rows[follower]["patron_gifts"][GIFT]["spent"] and rows[follower]["resonance"]["current"] == 14
        raise ToolError("Injected failure after all gateway writes")

    with (
        patch.object(db_mutations_resonance, "update_player_resonance", side_effect=fail_after_update) as injected,
        pytest.raises(ToolError, match="Injected failure after all gateway writes"),
    ):
        await cross(world, agent)
    injected.assert_awaited_once()
    assert await snapshot(world, agent) == before
    assert [await db_queries.get_player_at_patron_revision(pid) for pid in world.ids] == revisions
    assert (await cross(world, agent))["location"]["id"] == MILL


async def test_gateway_locks_earlier_party_member_before_follower(world):
    earlier, follower = sorted(world.ids)
    agent = await prepare(world, follower_index=world.ids.index(follower))
    async with asyncio.TaskGroup() as tasks:
        async with world.pool.acquire() as blocker, blocker.transaction():
            await charm(world, earlier, conn=blocker)
            crossing = tasks.create_task(refused_crossing(world, agent, follower))
            async with asyncio.timeout(5):
                while not await world.pool.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE $1 = ANY(pg_blocking_pids(pid)))",
                    blocker.get_server_pid(),
                ):
                    assert not crossing.done(), "Gateway did not wait for the locked party member"
                    await asyncio.sleep(0.01)
            async with world.pool.acquire() as observer, observer.transaction():
                assert (
                    await observer.fetchval(
                        "SELECT player_id FROM players WHERE player_id = $1 FOR UPDATE NOWAIT", follower
                    )
                    == follower
                )
    rows = await party_rows(world)
    assert {row["location_id"] for row in rows.values()} == {MARKET}
    assert GIFT not in rows[follower]["patron_gifts"] and rows[follower]["resonance"]["current"] == 9


async def refused_crossing(world, agent, follower):
    async with asyncio.timeout(10):
        with pytest.raises(ToolError, match="Host does not want to leave the Still"):
            await cross(world, agent, actor=follower)
