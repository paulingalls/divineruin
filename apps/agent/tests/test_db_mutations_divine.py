import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import db_mutations_divine


async def test_gain_writes_level_and_timestamp_in_one_statement():
    conn = AsyncMock()
    stamp = "2026-09-23T00:00:00+00:00"
    await db_mutations_divine.update_divine_favor("p", 15, last_served_at=stamp, conn=conn)
    conn.execute.assert_awaited_once()
    sql, player, level, served = conn.execute.call_args.args
    assert "UPDATE players" in sql
    assert "{divine_favor,level}" in sql
    assert "{divine_favor,last_served_at}" in sql
    assert player == "p" and json.loads(level) == 15 and json.loads(served) == stamp


async def test_non_gain_writes_only_level():
    conn = AsyncMock()
    await db_mutations_divine.update_divine_favor("p", 0, conn=conn)
    conn.execute.assert_awaited_once()
    sql, player, level = conn.execute.call_args.args
    assert "{divine_favor,last_served_at}" not in sql
    assert player == "p" and json.loads(level) == 0


async def test_decay_writes_level_and_decay_clock_in_one_statement():
    conn = AsyncMock()
    stamp = "2026-09-23T00:00:00+00:00"
    await db_mutations_divine.persist_favor_decay("p", 7, stamp, conn=conn)
    conn.execute.assert_awaited_once()
    sql, player, level, decay_at = conn.execute.call_args.args
    assert "{divine_favor,level}" in sql
    assert "{divine_favor,last_decay_at}" in sql
    assert "{divine_favor,last_served_at}" not in sql
    assert player == "p" and json.loads(level) == 7 and json.loads(decay_at) == stamp


async def _seed(pool, pid, favor):
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
        pid,
        json.dumps({"divine_favor": favor}),
    )


async def _read(pool, pid):
    row = await pool.fetchrow("SELECT data->'divine_favor' AS favor FROM players WHERE player_id=$1", pid)
    favor = row["favor"]
    return json.loads(favor) if isinstance(favor, str) else favor


async def test_gain_round_trip_in_postgres(dev_db_pool):
    pid = "s222_favor_gain"
    await _seed(dev_db_pool, pid, {"patron": "kaelen", "level": 10, "max": 100})
    try:
        stamp = datetime.now(UTC).isoformat()
        await db_mutations_divine.update_divine_favor(pid, 15, last_served_at=stamp, conn=dev_db_pool)
        favor = await _read(dev_db_pool, pid)
        assert favor["level"] == 15
        assert datetime.fromisoformat(favor["last_served_at"]) == datetime.fromisoformat(stamp)
    finally:
        await dev_db_pool.execute("DELETE FROM players WHERE player_id=$1", pid)


async def test_non_gain_preserves_timestamp_in_postgres(dev_db_pool):
    pid = "s222_favor_loss"
    stamp = "2026-09-01T00:00:00+00:00"
    await _seed(dev_db_pool, pid, {"patron": "kaelen", "level": 10, "max": 100, "last_served_at": stamp})
    try:
        await db_mutations_divine.update_divine_favor(pid, 0, conn=dev_db_pool)
        favor = await _read(dev_db_pool, pid)
        assert favor["level"] == 0
        assert favor["last_served_at"] == stamp
    finally:
        await dev_db_pool.execute("DELETE FROM players WHERE player_id=$1", pid)
