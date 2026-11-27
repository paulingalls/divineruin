"""Validate transactional rows with the same parsers used at process startup."""

import asyncio
import importlib
import json
from pathlib import Path

PYTHON_CATALOGS = (
    ("items", "weapon_proficiency", "validate_weapon_profile"),
    ("archetypes", "archetypes", "parse_archetype_row"),
    ("racial_resonance_bonuses", "racial_resonance", "parse_racial_resonance_row"),
    ("archetype_abilities", "abilities", "parse_ability_row"),
    ("archetype_milestones", "milestones", "parse_milestone_row"),
    ("mentor_variants", "mentor_variants", "parse_mentor_variant_row"),
    ("role_archetypes", "role_archetypes", "parse_role_archetype_row"),
    ("settlement_templates", "settlement_templates", "parse_settlement_template_row"),
    ("npcs", "npcs", "parse_npc_row"),
    ("companions", "companion_profiles", "parse_companion_row"),
    ("training_activity_types", "training_rules", "parse_activity_type_row"),
    (
        "hollowed_hallucinations",
        "hollowed_hallucinations",
        "parse_hollowed_hallucination_row",
    ),
)
SERVER_TABLES = (
    "locations",
    "spells",
    "creatures",
    "training_activity_types",
    "training_programs",
    "errand_templates",
    "recipes",
    "items",
    "archetypes",
    "archetype_abilities",
    "mentor_variants",
    "role_archetypes",
    "archetype_milestones",
    "pricing",
)


async def validate_runtime_catalogs(conn) -> None:
    tables = set(SERVER_TABLES) | {row[0] for row in PYTHON_CATALOGS}
    snapshot = {}
    for table in sorted(tables):
        rows = await conn.fetch(f"SELECT id, data FROM {table}")
        if not rows:
            raise ValueError(f"{table} produced no rows")
        snapshot[table] = [{"id": row["id"], "data": json.loads(row["data"])} for row in rows]
    await _validate_typescript(snapshot)
    spells = importlib.import_module("spells")
    creatures = [{"id": row["id"], "category": row["data"]["category"]} for row in snapshot["creatures"]]
    spells.set_spells(spells.parse_spell_catalog(snapshot["spells"], creatures))
    for table, name, parser in PYTHON_CATALOGS:
        module = importlib.import_module(name)
        for row in snapshot[table]:
            getattr(module, parser)(row["id"], row["data"])


async def _validate_typescript(snapshot: dict) -> None:
    command = Path(__file__).with_name("seed_catalogs.ts")
    process = await asyncio.create_subprocess_exec(
        "bun", "--no-env-file", "run", str(command), stdin=asyncio.subprocess.PIPE
    )
    await process.communicate(json.dumps(snapshot).encode())
    if process.returncode:
        raise ValueError("TypeScript runtime catalog validation failed")


async def invalidate_content_cache() -> None:
    command = Path(__file__).with_name("seed_cache.ts")
    process = await asyncio.create_subprocess_exec("bun", "--no-env-file", "run", str(command))
    try:
        async with asyncio.timeout(15):
            await process.wait()
        if process.returncode:
            raise RuntimeError("Valkey content-cache invalidation failed")
    except TimeoutError:
        raise RuntimeError("Valkey content-cache invalidation timed out") from None
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
