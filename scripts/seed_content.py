"""Seed content JSON files into PostgreSQL."""

import asyncio
import json
import os
import random
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import asyncpg

# The world-effect target vocabulary is owned by the agent (apps/agent/world_effect_targets.py)
# so the seeder's authoring-time check and the runtime resolution can never drift apart. This
# script runs from scripts/ with only apps/agent as its uv project, not on sys.path.
sys.path.insert(0, str(Path(__file__).parent.parent / "apps" / "agent"))

from creature_schema import validate_creature_stat_block
from dice import roll
from rules_engine import SKILL_TIER_ORDER, SKILLS
from world_effect_targets import is_valid_disposition_target

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
    "loot_tables.json": "loot_tables",
    "events.json": "events",
    "gods.json": "god_agent_state",
    "voice_registry.json": "voice_registry",
    "inventory_pools.json": "inventory_pools",
    "level_progression.json": "level_progression",
    "archetypes.json": "archetypes",
    "archetype_abilities.json": "archetype_abilities",
    "archetype_milestones.json": "archetype_milestones",
    "spells.json": "spells",
    "racial_resonance_bonuses.json": "racial_resonance_bonuses",
    "mentor_variants.json": "mentor_variants",
    "role_archetypes.json": "role_archetypes",
    "settlement_templates.json": "settlement_templates",
    "companions.json": "companions",
    "training_activity_types.json": "training_activity_types",
    "training_programs.json": "training_programs",
    "errand_templates.json": "errand_templates",
    "recipes.json": "recipes",
    "materials_catalog.json": "materials_catalog",
    "quality_outcomes.json": "quality_outcomes",
    "pricing.json": "pricing",
    "gathering_nodes.json": "gathering_nodes",
    "creatures.json": "creatures",
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


_MISPARSED_URL = "DATABASE_URL does not parse; percent-encode reserved characters in the password"


class _MinimumRoll(random.Random):
    def randint(self, a: int, b: int) -> int:
        return a


def validate_loot_table(table: dict) -> list[str]:
    """Validate authored loot data. M34 harvesting enforces requirements; loot rolls do not."""
    table_id = table.get("id", "?")
    errors: list[str] = []
    if not table.get("drops"):
        errors.append(f"Loot table '{table_id}' drops must be non-empty")
    if "hollow_residue" in table and type(table["hollow_residue"]) is not bool:
        errors.append(f"Loot table '{table_id}' hollow_residue must be a bool")
    for drop in table.get("drops", []):
        item_id = drop.get("item_id", "?")
        label = f"Loot table '{table_id}' drop '{item_id}'"
        chance = drop.get("chance")
        if type(chance) not in (int, float) or not 0 <= chance <= 1:
            errors.append(f"{label} chance must be in [0,1]")
        quantity = drop.get("quantity")
        if type(quantity) is int:
            if quantity < 1:
                errors.append(f"{label} quantity must be positive")
        elif isinstance(quantity, str):
            try:
                if roll(quantity, rng=_MinimumRoll()).total < 1:
                    errors.append(f"{label} quantity must have a positive minimum")
            except ValueError:
                errors.append(f"{label} quantity must be valid dice notation")
        else:
            errors.append(f"{label} quantity must be an int or dice notation")
        if "requires" not in drop:
            continue
        requirements = drop["requires"]
        if not isinstance(requirements, list):
            errors.append(f"{label} requires must be a list")
            continue
        for requirement in requirements:
            if not isinstance(requirement, dict) or set(requirement) != {
                "skill",
                "tier",
            }:
                errors.append(f"{label} requires entries must have skill and tier")
                continue
            if type(requirement["skill"]) is not str or requirement["skill"] not in SKILLS:
                errors.append(f"{label} unknown skill {requirement['skill']!r}")
            if type(requirement["tier"]) is not str or requirement["tier"] not in SKILL_TIER_ORDER:
                errors.append(f"{label} unknown tier {requirement['tier']!r}")
    return errors


def database_target(database_url: str) -> str:
    # A reserved character left unencoded in the password misparses the URL, and the refusal must
    # not print it: the parse's ValueError quotes what it misread (`from None` drops that from the
    # traceback), and an unencoded '/' can parse cleanly with the user read as the host, the digits
    # before the '/' as the port, and the rest of the password stranded, '@' and all, after the netloc
    # (in the path, or the query or fragment when it also holds a '?' or '#').
    try:
        parsed = urlsplit(database_url)
        port = parsed.port
    except ValueError:
        raise RuntimeError(_MISPARSED_URL) from None
    if "@" in parsed.path + parsed.query + parsed.fragment:
        raise RuntimeError(_MISPARSED_URL)
    database = parsed.path.lstrip("/")
    if not parsed.hostname or port is None or not database:
        raise RuntimeError("DATABASE_URL must include an explicit host, port, and database")
    return f"host={parsed.hostname} port={port} database={database}"


class InvalidContent(Exception):
    pass


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
        missing = [i for i, entity in enumerate(entities) if not entity.get(pk_field)]
        if missing:
            raise InvalidContent(f"{filename} row {missing[0]} has no {pk_field!r}")
        # The generated tier/level columns cast data to integer, so a bad creature must be caught
        # before insert or it aborts with a cast error instead of a field-named message.
        if table == "creatures":
            problems = [
                f"{entity.get('id', '?')}: {error}"
                for entity in entities
                for error in validate_creature_stat_block(entity)
            ]
            if problems:
                raise InvalidContent("\n".join(problems))
        for entity in entities:
            await conn.execute(query, entity[pk_field], json.dumps(entity))
        counts[table] = len(entities)
        print(f"  {table}: {len(entities)} entities")

    return counts


async def validate(conn: asyncpg.Connection) -> list[str]:
    errors: list[str] = []

    creature_rows = await conn.fetch("SELECT id, data FROM creatures")
    for row in creature_rows:
        errors.extend(f"{row['id']}: {error}" for error in validate_creature_stat_block(json.loads(row["data"])))

    rows = await conn.fetch("SELECT id, data FROM locations")
    location_ids = {row["id"] for row in rows}

    for row in rows:
        data = json.loads(row["data"])
        exits = data.get("exits", {})
        for direction, exit_info in exits.items():
            dest = exit_info.get("destination") if isinstance(exit_info, dict) else exit_info
            if dest not in location_ids:
                errors.append(f"Location '{row['id']}' exit '{direction}' references unknown destination '{dest}'")

    npc_rows = await conn.fetch("SELECT id, data FROM npcs")
    for row in npc_rows:
        data = json.loads(row["data"])
        knowledge = data.get("knowledge", {})
        tier_count = sum(1 for k in knowledge if k in ("free", "disposition >= friendly", "disposition >= trusted"))
        if tier_count < 2:
            errors.append(f"NPC '{row['id']}' has only {tier_count} knowledge tier(s), expected >= 2")

    # Cross-reference: encounter IDs in quest completion_conditions
    encounter_rows = await conn.fetch("SELECT id FROM encounter_templates")
    encounter_ids = {row["id"] for row in encounter_rows}

    item_rows = await conn.fetch("SELECT id FROM items")
    item_ids = {row["id"] for row in item_rows}

    npc_ids = {row["id"] for row in npc_rows}

    # Companions are their own entity (companions.json), not npcs rows, so world-effect
    # disposition targets validate against the npcs + companions id spaces.
    companion_rows = await conn.fetch("SELECT id FROM companions")
    companion_ids = {row["id"] for row in companion_rows}

    quest_rows = await conn.fetch("SELECT id, data FROM quests")
    for row in quest_rows:
        data = json.loads(row["data"])
        for stage in data.get("stages", []):
            # Check encounter references
            cc = stage.get("completion_conditions", {})
            encounter_ref = cc.get("encounter")
            if encounter_ref and encounter_ref not in encounter_ids:
                errors.append(
                    f"Quest '{row['id']}' stage '{stage.get('id', '?')}' references unknown encounter '{encounter_ref}'"
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
                    if not is_valid_disposition_target(shorthand, npc_ids, companion_ids):
                        errors.append(
                            f"Quest '{row['id']}' world_effect '{effect}' references "
                            f"unknown disposition target '{shorthand}'"
                        )

    material_rows = await conn.fetch("SELECT id FROM materials_catalog")
    material_ids = {row["id"] for row in material_rows}

    # Loot & currency (M4.7 story-002): every enemy must carry a category and a loot_table_id
    # that resolves to a loot_tables row.
    loot_rows = await conn.fetch("SELECT id, data FROM loot_tables")
    loot_table_ids = {row["id"] for row in loot_rows}
    for row in loot_rows:
        data = json.loads(row["data"])
        errors.extend(validate_loot_table(data))
        for drop in data.get("drops", []):
            item_ref = drop.get("item_id")
            owners = int(item_ref in item_ids) + int(item_ref in material_ids)
            if owners == 0:
                errors.append(f"Loot table '{row['id']}' references unknown drop '{item_ref}'")
            elif owners == 2:
                errors.append(f"Loot table '{row['id']}' references ambiguous drop '{item_ref}'")

    encounter_data_rows = await conn.fetch("SELECT id, data FROM encounter_templates")
    for row in encounter_data_rows:
        data = json.loads(row["data"])
        for enemy in data.get("enemies", []):
            enemy_id = enemy.get("id", "?")
            tier = enemy.get("tier")
            if type(tier) is not int or not 1 <= tier <= 4:
                errors.append(f"Encounter '{row['id']}' enemy '{enemy_id}' has invalid tier {tier!r}")
            if not enemy.get("category"):
                errors.append(f"Encounter '{row['id']}' enemy '{enemy_id}' is missing a 'category'")
            loot_ref = enemy.get("loot_table_id")
            if not loot_ref:
                errors.append(f"Encounter '{row['id']}' enemy '{enemy_id}' is missing a 'loot_table_id'")
            elif loot_ref not in loot_table_ids:
                errors.append(
                    f"Encounter '{row['id']}' enemy '{enemy_id}' references unknown loot_table_id '{loot_ref}'"
                )

    # Gathering (M4.8 story-015): every gathering_node's location_id must resolve to a locations row
    # and its resource_type to a materials_catalog row; every location resource_table entry must also
    # resolve to materials_catalog. Fail loud at seed (mirrors the loot_tables block) so a typo can't
    # ship a node sitting nowhere or granting a nonexistent material.
    node_rows = await conn.fetch("SELECT id, data FROM gathering_nodes")
    for row in node_rows:
        data = json.loads(row["data"])
        loc_ref = data.get("location_id")
        if loc_ref not in location_ids:
            errors.append(f"Gathering node '{row['id']}' references unknown location_id '{loc_ref}'")
        res_ref = data.get("resource_type")
        if res_ref not in material_ids:
            errors.append(f"Gathering node '{row['id']}' references unknown resource_type '{res_ref}'")

    for row in rows:
        data = json.loads(row["data"])
        for rarity, material_refs in (data.get("resource_table") or {}).items():
            for material_ref in material_refs:
                if material_ref not in material_ids:
                    errors.append(
                        f"Location '{row['id']}' resource_table '{rarity}' references unknown material '{material_ref}'"
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
            dest = exit_data.get("destination", "") if isinstance(exit_data, dict) else str(exit_data)
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
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be set to seed content")
    target = database_target(database_url)
    print(f"Target database: {target}")
    conn = await asyncpg.connect(database_url)

    try:
        async with conn.transaction():
            print("Seeding content...")
            try:
                counts = await seed(conn)
            except InvalidContent as error:
                print(f"Validation FAILED: {error}")
                sys.exit(1)

            print("\nSeeding map progress...")
            await seed_map_progress(conn)

            print("\nValidating...")
            errors = await validate(conn)
            if errors:
                print(f"\nValidation FAILED ({len(errors)} error(s)):")
                for err in errors:
                    print(f"  - {err}")
                sys.exit(1)
        total = sum(counts.values())
        print(f"\nDone: {total} entities seeded to {target}, all validations passed.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
