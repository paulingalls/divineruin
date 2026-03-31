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
    "scenes.json": "scenes",
    "quests.json": "quests",
    "factions.json": "factions",
    "lore_entries.json": "lore_entries",
    "players.json": "players",
    "npc_state.json": "npc_state",
    "encounter_templates.json": "encounter_templates",
    "events.json": "events",
    "gods.json": "god_agent_state",
    "voice_registry.json": "voice_registry",
    "inventory_pools.json": "inventory_pools",
}

PK_COLUMN = {
    "players": "player_id",
    "npc_state": "npc_id",
    "god_agent_state": "god_id",
    "voice_registry": "character_id",
}

UPSERT_SQL = """
    INSERT INTO {table} ({pk_col}, data)
    VALUES ($1, $2::jsonb)
    ON CONFLICT ({pk_col}) DO UPDATE SET data = $2::jsonb
"""


def upsert_query(table: str) -> str:
    if not re.match(r"^[a-z_]+$", table):
        raise ValueError(f"Invalid table name: {table}")
    pk_col = PK_COLUMN.get(table, "id")
    return UPSERT_SQL.format(table=table, pk_col=pk_col)


async def seed(conn: asyncpg.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for filename, table in TABLE_MAP.items():
        filepath = CONTENT_DIR / filename
        if not filepath.exists():
            print(f"  skip: {filename} (not found)")
            continue

        pk_field = PK_COLUMN.get(table, "id")
        query = upsert_query(table)
        entities = json.loads(filepath.read_text())
        for entity in entities:
            await conn.execute(query, entity[pk_field], json.dumps(entity))
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

    # Cross-reference: encounter IDs in quest completion_conditions
    encounter_rows = await conn.fetch("SELECT id FROM encounter_templates")
    encounter_ids = {row["id"] for row in encounter_rows}

    item_rows = await conn.fetch("SELECT id FROM items")
    item_ids = {row["id"] for row in item_rows}

    npc_ids = {row["id"] for row in npc_rows}

    effect_npc_map = {
        "torin": "guildmaster_torin", "yanna": "elder_yanna",
        "emris": "scholar_emris", "companion": "companion_kael",
    }

    quest_rows = await conn.fetch("SELECT id, data FROM quests")
    for row in quest_rows:
        data = json.loads(row["data"])
        for stage in data.get("stages", []):
            # Check encounter references
            cc = stage.get("completion_conditions", {})
            encounter_ref = cc.get("encounter")
            if encounter_ref and encounter_ref not in encounter_ids:
                errors.append(
                    f"Quest '{row['id']}' stage '{stage.get('id', '?')}' references "
                    f"unknown encounter '{encounter_ref}'"
                )

            # Check item references in completion_conditions
            for item_ref in cc.get("items", []):
                if item_ref not in item_ids:
                    errors.append(
                        f"Quest '{row['id']}' stage '{stage.get('id', '?')}' references "
                        f"unknown item '{item_ref}' in completion_conditions"
                    )

            # Check item references in rewards
            on_complete = stage.get("on_complete", {})
            for reward in on_complete.get("rewards", []):
                reward_item = reward.get("item") or reward.get("item_id")
                if reward_item and reward_item not in item_ids:
                    errors.append(
                        f"Quest '{row['id']}' stage '{stage.get('id', '?')}' references "
                        f"unknown reward item '{reward_item}'"
                    )

            # Check NPC shorthand in world_effects
            for effect in on_complete.get("world_effects", []):
                m = re.match(r"^(\w+)_disposition\s*[+-]\d+$", effect)
                if m:
                    shorthand = m.group(1)
                    resolved = effect_npc_map.get(shorthand, shorthand)
                    if resolved not in npc_ids:
                        errors.append(
                            f"Quest '{row['id']}' world_effect '{effect}' references "
                            f"unknown NPC '{resolved}'"
                        )

    return errors


async def seed_map_progress(conn: asyncpg.Connection) -> None:
    """Seed the starting location into player_map_progress for player_1."""
    # Read player_1's starting location and its exits
    players = json.loads((CONTENT_DIR / "players.json").read_text())
    locations = json.loads((CONTENT_DIR / "locations.json").read_text())
    location_map = {loc["id"]: loc for loc in locations}

    for player in players:
        player_id = player.get("player_id", "")
        location_id = player.get("location_id", "")
        if not player_id or not location_id:
            continue

        loc = location_map.get(location_id, {})
        exits = loc.get("exits", {})
        connections = []
        for exit_data in exits.values():
            if isinstance(exit_data, dict):
                dest = exit_data.get("destination", "")
            else:
                dest = str(exit_data)
            if dest:
                connections.append(dest)

        await conn.execute(
            """
            INSERT INTO player_map_progress (player_id, location_id, data)
            VALUES ($1, $2, $3::jsonb)
            ON CONFLICT (player_id, location_id) DO NOTHING
            """,
            player_id,
            location_id,
            json.dumps({"connections": connections}),
        )
        print(f"  map_progress: {player_id} @ {location_id} (connections: {connections})")


async def main() -> None:
    database_url = os.environ.get("DATABASE_URL", "postgresql://divineruin:divineruin@localhost:5432/divineruin")
    conn = await asyncpg.connect(database_url)

    try:
        print("Seeding content...")
        counts = await seed(conn)

        print("\nSeeding map progress...")
        await seed_map_progress(conn)

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
