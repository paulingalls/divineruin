import asyncio
import json
from uuid import uuid4

import pytest
from acceptance.seeds import seed_player

import event_types as E
from patron_deeds import judge_pending_deeds, mark_awarded, record_deed
from progression_tools import FavorGrant


async def read(conn, player_id):
    return json.loads(await conn.fetchval("SELECT data FROM players WHERE player_id=$1", player_id))


@pytest.fixture
async def player(dev_db_pool):
    player_id = f"deeds_{uuid4().hex}"
    await seed_player(dev_db_pool, player_id=player_id)
    await dev_db_pool.execute(
        "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1",
        player_id,
        json.dumps(
            {
                "sentinel": {"nested": [1, 2]},
                "divine_favor": {
                    "patron": "kaelen",
                    "level": 50,
                    "max": 100,
                    "last_whisper_level": 3,
                    "last_served_at": "2026-09-01T00:00:00+00:00",
                },
            }
        ),
    )
    try:
        yield dev_db_pool, player_id
    finally:
        await dev_db_pool.execute("DELETE FROM players WHERE player_id=$1", player_id)


async def judge(pool, player_id):
    events = []
    async with pool.acquire() as conn, conn.transaction():
        grant = await judge_pending_deeds(player_id, conn=conn, pending_events=events)
    return grant, events


@pytest.mark.parametrize(
    "patron,start,pending,awarded,amount,end",
    [
        ("kaelen", 50, ["won_combat", "fled_combat", "discovered_lore"], ["showed_courage"], -1, 49),
        ("kaelen", 99, ["won_combat"], [], 2, 100),
        ("kaelen", 1, ["fled_combat"], [], -3, 0),
        ("kaelen", 50, [], ["showed_courage"], 0, 50),
        ("veythar", 50, ["won_combat", "fled_combat"], [], 0, 50),
    ],
)
async def test_authored_judgment(player, patron, start, pending, awarded, amount, end):
    pool, pid = player
    await pool.execute(
        "UPDATE players SET data=jsonb_set(jsonb_set(data, '{divine_favor,patron}', $2::jsonb),"
        " '{divine_favor,level}', $3::jsonb) WHERE player_id=$1",
        pid,
        json.dumps(patron),
        json.dumps(start),
    )
    async with pool.acquire() as conn, conn.transaction():
        for kind in pending:
            await record_deed(pid, kind, conn=conn)
        for kind in awarded:
            await mark_awarded(pid, kind, conn=conn)
    before = await read(pool, pid)
    assert before["patron_deeds"] == {**dict.fromkeys(pending, "pending"), **dict.fromkeys(awarded, "awarded")}
    grant, events = await judge(pool, pid)
    if amount == 0:
        assert (grant, events) == (None, [])
        assert await read(pool, pid) == dict(before, patron_deeds={})
        return
    assert isinstance(grant, FavorGrant)
    assert (grant.previous_level, grant.new_level, grant.patron_id) == (start, end, patron)
    assert events == [
        (
            E.DIVINE_FAVOR_CHANGED,
            {
                "player_id": pid,
                "patron_id": patron,
                "previous_level": start,
                "new_level": end,
                "amount": end - start,
                "requested_amount": amount,
                "max": 100,
                "last_whisper_level": 3,
                "reason": "Patron deed judgment",
            },
        )
    ]
    after = await read(pool, pid)
    assert after["patron_deeds"] == {}
    assert after["divine_favor"]["level"] == end
    favor = dict(before["divine_favor"], level=end)
    if end > start:
        assert after["divine_favor"]["last_served_at"] > favor["last_served_at"]
        favor["last_served_at"] = after["divine_favor"]["last_served_at"]
    assert after == dict(before, divine_favor=favor, patron_deeds={})


@pytest.mark.parametrize("favor", [None, {"patron": "none", "level": 50}])
async def test_unbound_and_empty(player, favor):
    pool, pid = player
    await pool.execute("UPDATE players SET data=data - 'divine_favor' WHERE player_id=$1", pid)
    if favor is not None:
        await pool.execute(
            "UPDATE players SET data=jsonb_set(data, '{divine_favor}', $2::jsonb) WHERE player_id=$1",
            pid,
            json.dumps(favor),
        )
    before = await read(pool, pid)
    assert await judge(pool, pid) == (None, [])
    assert await read(pool, pid) == before
    async with pool.acquire() as conn, conn.transaction():
        await record_deed(pid, "won_combat", conn=conn)
    assert await judge(pool, pid) == (None, [])
    assert await read(pool, pid) == dict(before, patron_deeds={})


async def test_follower_ignores_autonomy(player):
    pool, pid = player
    async with pool.acquire() as conn, conn.transaction():
        for kind in ("won_alone", "succeeded_alone", "channeled_raw"):
            await record_deed(pid, kind, conn=conn)
    before = await read(pool, pid)
    assert before["patron_deeds"] == dict.fromkeys(("won_alone", "succeeded_alone", "channeled_raw"), "pending")
    assert await judge(pool, pid) == (None, [])
    assert await read(pool, pid) == dict(before, patron_deeds={})


async def test_repeated_deed_records_once(player):
    pool, pid = player
    async with pool.acquire() as conn, conn.transaction():
        for _ in range(3):
            await record_deed(pid, "won_combat", conn=conn)
        assert (await read(conn, pid))["patron_deeds"] == {"won_combat": "pending"}
    assert (await read(pool, pid))["patron_deeds"] == {"won_combat": "pending"}


async def test_rollback_and_unknown_kind(player):
    pool, pid = player
    async with pool.acquire() as conn, conn.transaction():
        await record_deed(pid, "won_combat", conn=conn)
    before = await read(pool, pid)
    with pytest.raises(RuntimeError, match="abort"):
        async with pool.acquire() as conn, conn.transaction():
            grant = await judge_pending_deeds(pid, conn=conn, pending_events=[])
            changed = await read(conn, pid)
            assert grant is not None and changed["divine_favor"]["level"] == 52
            assert changed["patron_deeds"] == {}
            raise RuntimeError("abort")
    assert await read(pool, pid) == before
    with pytest.raises(ValueError, match="unauthored"):
        async with pool.acquire() as conn, conn.transaction():
            await record_deed(pid, "unauthored", conn=conn)
    assert await read(pool, pid) == before


@pytest.mark.parametrize("operation", [record_deed, mark_awarded, judge_pending_deeds])
async def test_missing_player(dev_db_pool, operation):
    async with dev_db_pool.acquire() as conn, conn.transaction():
        with pytest.raises(ValueError, match="not found"):
            if operation == judge_pending_deeds:
                await operation("missing_deeds_player", conn=conn, pending_events=[])
            else:
                await operation("missing_deeds_player", "won_combat", conn=conn)


@pytest.mark.parametrize("patron", ["unknown_god", ""])
async def test_unknown_patron_preserves_journal(player, patron):
    pool, pid = player
    await pool.execute(
        "UPDATE players SET data=jsonb_set(data, '{divine_favor,patron}', $2::jsonb) WHERE player_id=$1",
        pid,
        json.dumps(patron),
    )
    async with pool.acquire() as conn, conn.transaction():
        await record_deed(pid, "won_combat", conn=conn)
    before = await read(pool, pid)
    with pytest.raises(ValueError, match="Unknown patron"):
        await judge(pool, pid)
    assert await read(pool, pid) == before


async def blocked(observer, task, waiter, holder):
    async with asyncio.timeout(5):
        while not await observer.fetchval("SELECT $1::int = ANY(pg_blocking_pids($2))", holder, waiter):
            if task.done():
                await task
                pytest.fail("contender finished without waiting for the row lock")
            await asyncio.sleep(0.01)


@pytest.mark.parametrize("unbound", [False, True])
@pytest.mark.parametrize("scenario", ["writer_first", "judge_first", "two_writers"])
async def test_concurrent_journal_operations(player, scenario, unbound):
    pool, pid = player
    positive, other = ("won_alone", "channeled_raw") if unbound else ("won_combat", "fled_combat")
    if unbound:
        await pool.execute(
            "UPDATE players SET data=jsonb_set(data, '{divine_favor,patron}', '\"none\"') WHERE player_id=$1", pid
        )
    async with pool.acquire() as a, pool.acquire() as b, pool.acquire() as observer:
        if scenario == "judge_first":
            await record_deed(pid, other, conn=a)
        tx = a.transaction()
        await tx.start()
        task = None
        try:
            if scenario == "judge_first":
                grant = await judge_pending_deeds(pid, conn=a, pending_events=[])
                assert grant is not None and grant.new_level == (2 if unbound else 47)
            else:
                await record_deed(pid, positive, conn=a)

            async def contender():
                async with b.transaction():
                    if scenario == "writer_first":
                        return await judge_pending_deeds(pid, conn=b, pending_events=[])
                    await record_deed(pid, positive if scenario == "judge_first" else other, conn=b)

            task = asyncio.create_task(contender())
            await blocked(observer, task, b.get_server_pid(), a.get_server_pid())
        finally:
            await tx.commit()
            if task is not None and not task.done():
                try:
                    async with asyncio.timeout(5):
                        await task
                finally:
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
        assert task is not None
        result = await task
    stored = await read(pool, pid)
    assert stored["sentinel"] == {"nested": [1, 2]}
    if unbound:
        assert (
            stored.get("unbound_autonomy", {"level": 0})["level"]
            == {"writer_first": 4, "judge_first": 2, "two_writers": 0}[scenario]
        )
    if scenario == "writer_first":
        assert result is not None and result.new_level == (4 if unbound else 52)
        assert stored["patron_deeds"] == {}
    else:
        expected = {positive: "pending"}
        if scenario == "two_writers":
            expected[other] = "pending"
        assert stored["patron_deeds"] == expected
        grant, events = await judge(pool, pid)
        assert grant is not None and grant.new_level == (6 if unbound else 49)
        if unbound:
            assert events == []
        else:
            assert events[0][1]["amount"] == (2 if scenario == "judge_first" else -1)
    settled = await read(pool, pid)
    assert settled["unbound_autonomy" if unbound else "divine_favor"]["level"] == (
        (4 if scenario == "writer_first" else 6) if unbound else (52 if scenario == "writer_first" else 49)
    )
    assert await judge(pool, pid) == (None, [])
    assert await read(pool, pid) == settled
