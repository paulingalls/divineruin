import asyncio
import importlib
import json
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))
seed_content = importlib.import_module("seed_content")


def test_catalog_columns_and_indexes(fresh_migrated_db):
    async def check():
        conn = await asyncpg.connect(fresh_migrated_db)
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
