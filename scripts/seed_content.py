"""Seed content JSON files into PostgreSQL."""

import asyncio
import json
import os
import re
import sys
from pathlib import Path

import asyncpg

CONTENT_DIR = Path(__file__).parent.parent / "content"

TABLE_MAP = {
    "locations.json": "locations",
    "npcs.json": "npcs",
    "items.json": "items",
    "quests.json": "quests",
    "factions.json": "factions",
    "lore_entries.json": "lore_entries",
}

UPSERT_SQL = """
    INSERT INTO {table} (id, data)
    VALUES ($1, $2::jsonb)
    ON CONFLICT (id) DO UPDATE SET data = $2::jsonb
"""


def upsert_query(table: str) -> str:
    if not re.match(r"^[a-z_]+$", table):
        raise ValueError(f"Invalid table name: {table}")
    return UPSERT_SQL.format(table=table)


async def seed(conn: asyncpg.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for filename, table in TABLE_MAP.items():
        filepath = CONTENT_DIR / filename
        if not filepath.exists():
            print(f"  skip: {filename} (not found)")
            continue

        query = upsert_query(table)
        entities = json.loads(filepath.read_text())
        for entity in entities:
            await conn.execute(query, entity["id"], json.dumps(entity))
        counts[table] = len(entities)
        print(f"  {table}: {len(entities)} entities")

    return counts


async def validate(conn: asyncpg.Connection) -> list[str]:
    errors: list[str] = []

    rows = await conn.fetch("SELECT id, data FROM locations")
    location_ids = {row["id"] for row in rows}

    for row in rows:
        data = json.loads(row["data"])
        exits = data.get("exits", {})
        for direction, exit_info in exits.items():
            dest = exit_info.get("destination") if isinstance(exit_info, dict) else exit_info
            if dest not in location_ids:
                errors.append(
                    f"Location '{row['id']}' exit '{direction}' references "
                    f"unknown destination '{dest}'"
                )

    npc_rows = await conn.fetch("SELECT id, data FROM npcs")
    for row in npc_rows:
        data = json.loads(row["data"])
        knowledge = data.get("knowledge", {})
        tier_count = sum(1 for k in knowledge if k in ("free", "disposition >= friendly", "disposition >= trusted"))
        if tier_count < 2:
            errors.append(
                f"NPC '{row['id']}' has only {tier_count} knowledge tier(s), expected >= 2"
            )

    return errors


async def main() -> None:
    database_url = os.environ.get("DATABASE_URL", "postgresql://divineruin:divineruin@localhost:5432/divineruin")
    conn = await asyncpg.connect(database_url)

    try:
        print("Seeding content...")
        counts = await seed(conn)

        print("\nValidating...")
        errors = await validate(conn)

        if errors:
            print(f"\nValidation FAILED ({len(errors)} error(s)):")
            for err in errors:
                print(f"  - {err}")
            sys.exit(1)
        else:
            total = sum(counts.values())
            print(f"\nDone: {total} entities seeded, all validations passed.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
