import asyncio
import importlib
import json
import os
import sys
from pathlib import Path

import asyncpg
import pytest
from testcontainers.postgres import PostgresContainer

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
seed_content = importlib.import_module("seed_content")


@pytest.fixture
def migrated_db():
    os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")
    with PostgresContainer("postgres:16-alpine") as pg:
        dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")

        async def migrate():
            conn = await asyncpg.connect(dsn)
            try:
                for path in sorted((ROOT / "scripts/migrations").glob("*.sql")):
                    await conn.execute(path.read_text())
            finally:
                await conn.close()

        asyncio.run(migrate())
        yield dsn


def test_catalog_columns_and_indexes(migrated_db):
    async def check():
        conn = await asyncpg.connect(migrated_db)
        try:
            indexes = await conn.fetch("SELECT indexdef FROM pg_indexes WHERE tablename = 'creatures'")
            definitions = "\n".join(row["indexdef"] for row in indexes)
            for column in ("category", "tier", "name"):
                assert f"({column})" in definitions
            await seed_content.seed(conn)
            rows = await conn.fetch("SELECT id, data, name, category, tier, level FROM creatures ORDER BY id")
            assert {row["id"] for row in rows} == {"hollow_shadeling", "hollow_hollowmoth"}
            for row in rows:
                data = json.loads(row["data"])
                assert (row["name"], row["category"], row["tier"], row["level"]) == (
                    data["name"],
                    data["category"],
                    data["tier"],
                    data["level"],
                )
            damaged = json.loads(rows[0]["data"])
            damaged["attacks"][0]["damage"] = 4
            await conn.execute(
                "UPDATE creatures SET data = $2::jsonb WHERE id = $1", rows[0]["id"], json.dumps(damaged)
            )
            assert f"{rows[0]['id']}: attacks[0].damage: expected string" in await seed_content.validate(conn)
        finally:
            await conn.close()

    asyncio.run(check())
