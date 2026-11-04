"""Upgrade real pre-taint inventory through the shipped migrator."""

import asyncio
import os
import shutil
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import asyncpg


async def test_upgrade_preserves_stacks_and_revision(postgres_container, tmp_path):
    root = Path(__file__).resolve().parents[4]
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    shutil.copy(root / "scripts/migrate.ts", tmp_path / "migrate.ts")
    for source in sorted((root / "scripts/migrations").glob("*.sql")):
        if source.name < "061":
            shutil.copy(source, migrations)
    name = f"taint_upgrade_{uuid4().hex}"
    admin = await asyncpg.connect(postgres_container)
    await admin.execute(f'CREATE DATABASE "{name}"')
    dsn = urlunsplit(urlsplit(postgres_container)._replace(path=f"/{name}"))

    async def migrate():
        process = await asyncio.create_subprocess_exec(
            "bun",
            str(tmp_path / "migrate.ts"),
            env={**os.environ, "DATABASE_URL": dsn},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output, _ = await process.communicate()
        assert process.returncode == 0, output.decode()

    conn = None
    try:
        await migrate()
        conn = await asyncpg.connect(dsn)
        await conn.execute("INSERT INTO players (player_id,data) VALUES ('a','{}'),('b','{}')")
        await conn.execute("""INSERT INTO player_inventory (player_id,item_id,data) VALUES
            ('a','rend_shard','{"quantity":2,"equipped":false}'),
            ('b','oak_wood','{"quantity":7,"current_hits":4}')""")
        original = await conn.fetch("SELECT player_id,item_id,data FROM player_inventory ORDER BY player_id")
        revisions = dict(await conn.fetch("SELECT player_id,inventory_revision FROM players ORDER BY player_id"))
        source = root / "scripts/migrations/061_inventory_tainted.sql"
        assert source.exists(), "061 inventory stack migration is missing"
        shutil.copy(source, migrations)
        await migrate()
        assert await conn.fetch("SELECT player_id,item_id,data FROM player_inventory ORDER BY player_id") == original
        assert await conn.fetchval("SELECT bool_and(tainted = false) FROM player_inventory") is True
        assert (
            dict(await conn.fetch("SELECT player_id,inventory_revision FROM players ORDER BY player_id")) == revisions
        )
        statements = [
            "INSERT INTO player_inventory (player_id,item_id,tainted,data) VALUES ('a','rend_shard',true,'{\"quantity\":1}')",
            "UPDATE player_inventory SET data='{\"quantity\":3}' WHERE player_id='a' AND tainted",
            "DELETE FROM player_inventory WHERE player_id='a' AND tainted",
        ]
        for index, statement in enumerate(statements, 1):
            await conn.execute(statement)
            assert (
                await conn.fetchval("SELECT inventory_revision FROM players WHERE player_id='a'")
                == revisions["a"] + index
            )
            assert (
                await conn.fetch(
                    "SELECT player_id,item_id,data FROM player_inventory WHERE NOT tainted ORDER BY player_id"
                )
                == original
            )
        await migrate()
        assert await conn.fetchval("SELECT count(*) FROM _migrations WHERE name='061_inventory_tainted.sql'") == 1
    finally:
        if conn:
            await conn.close()
        await admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        await admin.close()
