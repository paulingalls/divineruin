"""Archetype chassis — DB-loaded content config (M2.1).

content/archetypes.json is the single source of truth for the 18 archetype
chassis (HP, resource formulas, save/armor/weapon proficiencies, starting
skills), folding the previously scattered code constants. This is the
foundational module: hp_scaling and rules_engine import FROM it (it imports
nothing from them), so the HP/resource math derives from the loaded chassis
with no import cycle.

Mirrors training_rules.py: a plain module-global dict populated by
load_archetypes() at worker startup (or set_archetypes() in tests), a fail-loud
parse_archetype_row shared by the DB loader and the JSON test fixture, and a
sync get_archetype_chassis accessor (pure math needs in-memory lookup, not the
Redis-cached recipes.py idiom — only 18 static rows).
"""

import json
import logging
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger("divineruin.archetypes")

HPCategory = Literal["martial", "primal_divine", "arcane_shadow"]
ResourcePattern = Literal["stamina_only", "focus_only", "focus_primary", "split"]


@dataclass(frozen=True)
class PoolFormula:
    base: int  # 4, 5, 6, or 8
    attribute: str  # "strength", "constitution", etc.
    level_divisor: int  # 1=+level, 2=+level//2, 3=+level//3, 0=flat


@dataclass(frozen=True)
class ResourceConfig:
    pattern: ResourcePattern
    stamina_formula: PoolFormula | None  # None = archetype has no stamina pool
    focus_formula: PoolFormula | None  # None = archetype has no focus pool


@dataclass(frozen=True)
class Chassis:
    id: str
    hp_base: int
    hp_growth: int
    hp_category: HPCategory
    resource: ResourceConfig
    save_proficiencies: tuple[str, ...]
    armor_proficiencies: tuple[str, ...]
    weapon_proficiencies: tuple[str, ...]
    skill_options: tuple[str, ...]
    num_skill_choices: int


# Module-level runtime-loaded chassis. Populated by load_archetypes() at worker
# startup, or by set_archetypes() in tests.
_archetypes: dict[str, Chassis] = {}


def _parse_formula(raw: object, ctx: str) -> PoolFormula | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx} is not an object or null")
    return PoolFormula(
        base=raw["base"],
        attribute=raw["attribute"],
        level_divisor=raw["level_divisor"],
    )


def parse_archetype_row(archetype_id: str, data: dict) -> Chassis:
    """Parse a raw dict (from JSON file or DB JSONB) into a Chassis.

    Shared by load_archetypes (DB) and tests/archetypes_config_fixture (JSON).
    Raises ValueError wrapping the underlying error with the row id for context.
    """
    try:
        hp = data["hp"]
        resource = data["resource"]
        skills = data["starting_skills"]
        return Chassis(
            id=archetype_id,
            hp_base=hp["base"],
            hp_growth=hp["growth"],
            hp_category=hp["category"],
            resource=ResourceConfig(
                pattern=resource["pattern"],
                stamina_formula=_parse_formula(resource["stamina_formula"], f"{archetype_id}.resource.stamina_formula"),
                focus_formula=_parse_formula(resource["focus_formula"], f"{archetype_id}.resource.focus_formula"),
            ),
            save_proficiencies=tuple(data["save_proficiencies"]),
            armor_proficiencies=tuple(data["armor_proficiencies"]),
            weapon_proficiencies=tuple(data["weapon_proficiencies"]),
            skill_options=tuple(skills["options"]),
            num_skill_choices=skills["num_choices"],
        )
    except (KeyError, TypeError) as e:
        raise ValueError(f"Malformed archetypes row {archetype_id!r}: {e}") from e


def set_archetypes(config: dict[str, Chassis]) -> None:
    """Test seam: populate _archetypes directly without going through the DB."""
    _archetypes.clear()
    _archetypes.update(config)


def get_archetype_chassis(archetype_id: str) -> Chassis:
    """Return the chassis for an archetype id. Raises ValueError if not loaded."""
    if archetype_id not in _archetypes:
        raise ValueError(f"Unknown archetype: {archetype_id!r}")
    return _archetypes[archetype_id]


async def load_archetypes() -> None:
    """Load the archetype chassis from the DB into _archetypes.

    Called from async_worker startup. Fails loud if the query errors —
    HP/resource math depends on this map being populated.
    """
    import db

    pool = await db.get_pool()
    rows = await pool.fetch("SELECT id, data FROM archetypes")
    _archetypes.clear()
    for row in rows:
        data = json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]
        _archetypes[row["id"]] = parse_archetype_row(row["id"], data)
    logger.info("Loaded %d archetype chassis", len(_archetypes))
