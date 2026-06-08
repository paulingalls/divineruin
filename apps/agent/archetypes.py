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
from typing import Literal, get_args

logger = logging.getLogger("divineruin.archetypes")

HPCategory = Literal["martial", "primal_divine", "arcane_shadow"]
ResourcePattern = Literal["stamina_only", "focus_only", "focus_primary", "split"]
# The archetype's magic source binding (M8). Single source for the primary casters,
# "cross" for Bard; null/absent for pure martials (no magic). "cross" and the spell
# catalog's SpellSource intentionally differ — only single sources index the catalog.
MagicSource = Literal["arcane", "divine", "primal", "cross"]

# Closed vocabularies for the chassis enums — the loader owns fail-loud validation
# (constraint chassis-row-shape-contract), mirroring the TS parseArchetypeRow.
_HP_CATEGORIES = frozenset(get_args(HPCategory))
_RESOURCE_PATTERNS = frozenset(get_args(ResourcePattern))
_MAGIC_SOURCES = frozenset(get_args(MagicSource))


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
    magic_source: str | None = None  # M8: arcane/divine/primal/cross; None for pure martials


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
        if hp["category"] not in _HP_CATEGORIES:
            raise ValueError(
                f"archetype {archetype_id!r} hp.category {hp['category']!r} not in {sorted(_HP_CATEGORIES)}"
            )
        if resource["pattern"] not in _RESOURCE_PATTERNS:
            raise ValueError(
                f"archetype {archetype_id!r} resource.pattern {resource['pattern']!r} not in {sorted(_RESOURCE_PATTERNS)}"
            )
        # magic_source is optional (absent/null for pure martials); validate the vocab when present.
        magic_source = data.get("magic_source")
        if magic_source is not None and magic_source not in _MAGIC_SOURCES:
            raise ValueError(
                f"archetype {archetype_id!r} magic_source {magic_source!r} not in {sorted(_MAGIC_SOURCES)}"
            )
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
            magic_source=magic_source,
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


def is_loaded() -> bool:
    """True once the chassis has been populated (startup load or test seam).

    Lets an entry point load once per process and skip redundant DB reads —
    both the async worker AND the LiveKit agent use the chassis (the agent via
    award_xp/update_quest -> calculate_max_hp), so each must load it at startup.
    """
    return bool(_archetypes)


async def load_archetypes() -> None:
    """Load the archetype chassis from the DB into _archetypes.

    Called from async_worker startup. Fails loud if the query errors —
    HP/resource math depends on this map being populated.
    """
    import db

    pool = await db.get_pool()
    rows = await pool.fetch("SELECT id, data FROM archetypes")
    # Build into a local dict first, then swap in one synchronous step. A
    # malformed row fails loud WITHOUT wiping an already-loaded chassis, and the
    # clear+update has no await between it, so a concurrent get_archetype_chassis
    # never observes a half-populated map.
    loaded: dict[str, Chassis] = {}
    for row in rows:
        data = json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]
        loaded[row["id"]] = parse_archetype_row(row["id"], data)
    _archetypes.clear()
    _archetypes.update(loaded)
    logger.info("Loaded %d archetype chassis", len(_archetypes))
