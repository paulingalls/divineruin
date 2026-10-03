"""Real PostgreSQL revision ordering, rollback, transfer and cross-language capture."""

import asyncio
import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

import db_queries
from inventory_refresh import inventory_payload


@pytest.fixture
async def owners(dev_db_pool):
    pool = dev_db_pool
    ids = [f"revision_{uuid4().hex}" for _ in range(2)]
    for pid in ids:
        await pool.execute("INSERT INTO players(player_id,data) VALUES($1,'{}')", pid)
    try:
        yield pool, ids
    finally:
        await pool.execute("DELETE FROM players WHERE player_id = ANY($1)", ids)


async def write(conn, pid, quantity):
    await conn.execute(
        "INSERT INTO player_inventory(player_id,item_id,data) VALUES($1,'oak_wood',$2::jsonb) "
        "ON CONFLICT(player_id,item_id) DO UPDATE SET data=excluded.data",
        pid,
        json.dumps({"quantity": quantity}),
    )


async def test_revision_empty_rollback_transfer_and_bun_agree(owners, tmp_path):
    pool, (owner, other) = owners
    assert await inventory_payload(owner) == {"player_id": owner, "inventory_revision": "0", "inventory": []}
    async with pool.acquire() as conn:
        transaction = conn.transaction()
        await transaction.start()
        await write(conn, owner, 1)
        buffered = await inventory_payload(owner, conn=conn)
        assert buffered["inventory_revision"] == "1"
        await transaction.commit()
        await conn.execute("UPDATE players SET inventory_revision=9007199254740992 WHERE player_id=$1", owner)
        await write(conn, owner, 3)
        current = await inventory_payload(owner, conn=conn)
        assert current["inventory_revision"] == "9007199254740993"
        transaction = conn.transaction()
        await transaction.start()
        await write(conn, owner, 4)
        assert (await inventory_payload(owner, conn=conn))["inventory_revision"] == "9007199254740994"
        await transaction.rollback()
        assert await inventory_payload(owner, conn=conn) == current
        path = tmp_path / "freshness.json"
        path.write_text(json.dumps({"buffered": buffered, "current": current}))
        bridge = await asyncio.to_thread(
            subprocess.run,
            ["bun", "--preload", "./test-preload.ts", "scripts/inventory-db-bridge.ts"],
            cwd=Path(__file__).resolve().parents[3] / "apps/mobile",
            env={**os.environ, "INVENTORY_FRESHNESS_FIXTURE": str(path)},
            capture_output=True,
            text=True,
        )
        assert bridge.returncode == 0, bridge.stdout + bridge.stderr
        await conn.execute("UPDATE player_inventory SET player_id=$2 WHERE player_id=$1", owner, other)
        assert await inventory_payload(owner, conn=conn) == {
            "player_id": owner,
            "inventory_revision": "9007199254740994",
            "inventory": [],
        }
        transferred = await inventory_payload(other, conn=conn)
        assert transferred["inventory_revision"] == "1"
        assert transferred["inventory"][0]["slot_info"]["quantity"] == 3
        await conn.execute("DELETE FROM player_inventory WHERE player_id=$1", other)
        assert await inventory_payload(other, conn=conn) == {
            "player_id": other,
            "inventory_revision": "2",
            "inventory": [],
        }


async def wait_for_lock(pool, pid):
    async with asyncio.timeout(5):
        while True:
            waiting = await pool.fetchval("SELECT wait_event_type FROM pg_stat_activity WHERE pid=$1", pid)
            if waiting == "Lock":
                return
            await asyncio.sleep(0.01)


@pytest.mark.parametrize("lock", ["owner", "inventory"])
async def test_held_real_lock_serializes_committed_versions(owners, lock):
    pool, (owner, _) = owners
    await write(pool, owner, 1)
    async with pool.acquire() as first, pool.acquire() as second:
        transaction = first.transaction()
        await transaction.start()
        table = "players" if lock == "owner" else "player_inventory"
        await first.fetch(f"SELECT * FROM {table} WHERE player_id=$1 FOR UPDATE", owner)
        pending = asyncio.create_task(write(second, owner, 3))
        try:
            await wait_for_lock(pool, second.get_server_pid())
            if lock == "owner":
                assert (await inventory_payload(owner, conn=first))["inventory_revision"] == "1"
            else:
                await write(first, owner, 2)
                assert (await inventory_payload(owner, conn=first))["inventory_revision"] == "2"
            await transaction.commit()
            await asyncio.wait_for(pending, 5)
        finally:
            if not pending.done():
                pending.cancel()
            if first.is_in_transaction():
                await transaction.rollback()
        result = await inventory_payload(owner, conn=second)
        assert result["inventory_revision"] == ("2" if lock == "owner" else "3")
        assert result["inventory"][0]["slot_info"]["quantity"] == 3


async def test_python_capture_uses_one_mvcc_statement(owners):
    pool, (owner, _) = owners
    await write(pool, owner, 1)

    class Boundary:
        calls = 0

        async def fetch(self, query, *args):
            self.calls += 1
            rows = await pool.fetch(query, *args)
            if self.calls == 1:
                await write(pool, owner, 3)
            return rows

    boundary = Boundary()
    captured = await db_queries.get_inventory_snapshot(owner, conn=boundary)
    assert boundary.calls == 1
    assert captured["inventory_revision"] == "1"
    assert captured["inventory"][0]["slot_info"]["quantity"] == 1
    assert (await inventory_payload(owner))["inventory_revision"] == "2"


async def test_opposite_owner_transfers_serialize_without_lost_revision(owners):
    pool, (one, two) = owners
    await write(pool, one, 1)
    await pool.execute(
        "INSERT INTO player_inventory(player_id,item_id,data) VALUES($1,'wolf_pelt','{\"quantity\":2}')", two
    )
    async with pool.acquire() as first, pool.acquire() as second:
        tx1, tx2 = first.transaction(), second.transaction()
        await tx1.start()
        await tx2.start()
        await first.fetch("SELECT * FROM player_inventory WHERE player_id=$1 FOR UPDATE", one)
        await second.fetch("SELECT * FROM player_inventory WHERE player_id=$1 FOR UPDATE", two)

        async def transfer(conn, tx, source, dest):
            try:
                await conn.execute("UPDATE player_inventory SET player_id=$2 WHERE player_id=$1", source, dest)
                await tx.commit()
            except BaseException:
                await tx.rollback()
                raise

        await asyncio.wait_for(asyncio.gather(transfer(first, tx1, one, two), transfer(second, tx2, two, one)), 5)
    result1, result2 = await inventory_payload(one), await inventory_payload(two)
    assert result1["inventory_revision"] == result2["inventory_revision"] == "3"
    assert result1["inventory"][0]["id"] == "wolf_pelt"
    assert result2["inventory"][0]["id"] == "oak_wood"


async def test_owner_first_and_inventory_first_lock_order_aborts_loudly(owners):
    import asyncpg

    pool, (owner, _) = owners
    await write(pool, owner, 1)
    async with pool.acquire() as first, pool.acquire() as second:
        tx1, tx2 = first.transaction(), second.transaction()
        await tx1.start()
        await tx2.start()
        await first.fetch("SELECT * FROM players WHERE player_id=$1 FOR UPDATE", owner)
        await second.fetch("SELECT * FROM player_inventory WHERE player_id=$1 FOR UPDATE", owner)

        async def competing():
            try:
                await write(second, owner, 3)
                await tx2.commit()
            except asyncpg.DeadlockDetectedError as error:
                await tx2.rollback()
                return error
            return None

        pending = asyncio.create_task(competing())
        await wait_for_lock(pool, second.get_server_pid())
        failure = None
        try:
            await write(first, owner, 2)
        except asyncpg.DeadlockDetectedError as error:
            failure = error
        finally:
            await tx1.rollback()
        other_failure = await asyncio.wait_for(pending, 5)
        assert isinstance(failure or other_failure, asyncpg.DeadlockDetectedError)


@pytest.mark.parametrize("scan", ["sequential", "index"])
@pytest.mark.parametrize("producer", ["python", "bun"])
async def test_snapshot_order_is_stable_across_query_plans(owners, scan, producer):
    pool, (owner, _) = owners
    item_ids = ["oak_wood", "crystal_flask", "medicinal_herb"]
    for item_id in item_ids:
        await pool.execute(
            "INSERT INTO player_inventory(player_id,item_id,data) VALUES($1,$2,'{\"quantity\":1}')",
            owner,
            item_id,
        )
    settings = (
        "SET LOCAL enable_seqscan=on; SET LOCAL enable_indexscan=off; "
        "SET LOCAL enable_indexonlyscan=off; SET LOCAL enable_bitmapscan=off"
        if scan == "sequential"
        else "SET LOCAL enable_seqscan=off; SET LOCAL enable_indexscan=on; "
        "SET LOCAL enable_indexonlyscan=on; SET LOCAL enable_bitmapscan=off"
    )
    settings += "; SET LOCAL enable_hashjoin=off; SET LOCAL enable_mergejoin=off; SET LOCAL join_collapse_limit=1"
    if producer == "python":
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(settings)

            class ObservedConnection:
                async def fetch(self, query, *args):
                    plan = json.loads(await conn.fetchval("EXPLAIN (FORMAT JSON) " + query, *args))[0]["Plan"]
                    nodes = [plan]
                    scans = []
                    while nodes:
                        node = nodes.pop()
                        if node.get("Relation Name") == "player_inventory":
                            scans.append(node["Node Type"])
                        nodes.extend(node.get("Plans", []))
                    assert scans == (["Seq Scan"] if scan == "sequential" else ["Index Scan"])
                    return await conn.fetch(query, *args)

            snapshot = await db_queries.get_inventory_snapshot(owner, conn=ObservedConnection())
            inventory = await db_queries.get_player_inventory(owner, conn=conn)
        assert inventory == snapshot["inventory"]
    else:
        code = """
import { SQL } from 'bun';
import { inventorySnapshot } from './apps/server/src/inventory_snapshot.ts';
const sql = new SQL(process.env.DATABASE_URL);
try {
  const result = await sql.begin(async tx => {
    await tx.unsafe(process.env.INVENTORY_SCAN_SETTINGS);
    return inventorySnapshot(process.env.INVENTORY_SCAN_OWNER, tx);
  });
  console.log(JSON.stringify(result));
} finally { await sql.close(); }
"""
        process = await asyncio.to_thread(
            subprocess.run,
            ["bun", "-e", code],
            cwd=Path(__file__).resolve().parents[3],
            env={**os.environ, "INVENTORY_SCAN_SETTINGS": settings, "INVENTORY_SCAN_OWNER": owner},
            capture_output=True,
            text=True,
        )
        assert process.returncode == 0, process.stdout + process.stderr
        snapshot = json.loads(process.stdout)
    assert snapshot["player_id"] == owner
    assert snapshot["inventory_revision"] == "3"
    assert [row["id"] for row in snapshot["inventory"]] == sorted(item_ids)
    assert all(row["slot_info"]["quantity"] == 1 for row in snapshot["inventory"])
