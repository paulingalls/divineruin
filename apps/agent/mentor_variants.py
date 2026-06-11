"""Mentor variants — DB-loaded content config (M9 / story-001).

content/mentor_variants.json is the single source of truth for martial style
VARIANTS: a mentor-taught variant of a base elective technique that fully
overrides the technique's cost/effect/narration on activation and carries a
cultural-attribution string for the DM voice. This module is the Python loader,
an exact mirror of spells.py/abilities.py: a module-global dict populated by
load_mentor_variants() at process startup (or set_mentor_variants() in tests), a
fail-loud parse_mentor_variant_row shared by the DB loader and the JSON test
fixture, and sync accessors.

A variant is FULLY specified (decision m9 override shape): its cost is the same
Cost{stamina, focus, scaling} object the abilities layer uses (reused from
abilities, not redefined), so the activation path (story-003) can swap a
variant's values in wholesale. Each variant keys to a base ability_id (a martial
elective) and a teaching mentor NPC. Downstream: training unlock (story-002),
activation override + cultural narration (story-003).
"""

import json
import logging
from dataclasses import dataclass

from abilities import Cost
from catalog_parse import parse_str

logger = logging.getLogger("divineruin.mentor_variants")


@dataclass(frozen=True)
class MentorVariant:
    id: str
    ability_id: str
    mentor_id: str
    cost: Cost
    effect: str
    narration_cue: str
    cultural_attribution: str


# Module-level runtime-loaded variants, keyed by variant id. Populated by
# load_mentor_variants() at startup, or by set_mentor_variants() in tests.
_mentor_variants: dict[str, MentorVariant] = {}


def _parse_cost(raw: object, ctx: str) -> Cost:
    """Parse the variant cost into the shared Cost shape, fail-loud.

    Mirrors abilities._parse_cost — each loader owns its own fail-loud validation
    for cross-language parity (the same discipline the abilities/spells loaders
    follow), so this small parse is intentional symmetry, not duplication.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx} is not an object")
    stamina = raw["stamina"]
    focus = raw["focus"]
    scaling = raw["scaling"]
    # bool is a subclass of int — exclude it explicitly, parity with the TS guard.
    if not isinstance(stamina, int) or isinstance(stamina, bool):
        raise ValueError(f"{ctx}.stamina is not an int")
    if not isinstance(focus, int) or isinstance(focus, bool):
        raise ValueError(f"{ctx}.focus is not an int")
    if scaling is not None and not isinstance(scaling, str):
        raise ValueError(f"{ctx}.scaling is not a string or null")
    return Cost(stamina=stamina, focus=focus, scaling=scaling)


def parse_mentor_variant_row(variant_id: str, data: dict) -> MentorVariant:
    """Parse a raw dict (from JSON file or DB JSONB) into a MentorVariant.

    Shared by load_mentor_variants (DB) and the JSON test fixture. Raises
    ValueError wrapping the underlying error with the row id for context; owns
    fail-loud validation of the cost shape and the required string fields.
    """
    try:
        return MentorVariant(
            id=variant_id,
            ability_id=parse_str(data["ability_id"], f"{variant_id}.ability_id"),
            mentor_id=parse_str(data["mentor_id"], f"{variant_id}.mentor_id"),
            cost=_parse_cost(data["cost"], f"{variant_id}.cost"),
            effect=parse_str(data["effect"], f"{variant_id}.effect"),
            narration_cue=parse_str(data["narration_cue"], f"{variant_id}.narration_cue"),
            cultural_attribution=parse_str(data["cultural_attribution"], f"{variant_id}.cultural_attribution"),
        )
    except (KeyError, TypeError) as e:
        raise ValueError(f"Malformed mentor_variants row {variant_id!r}: {e}") from e


def set_mentor_variants(config: dict[str, MentorVariant]) -> None:
    """Test seam: populate _mentor_variants directly without going through the DB."""
    _mentor_variants.clear()
    _mentor_variants.update(config)


def get_mentor_variant(variant_id: str) -> MentorVariant:
    """Return the variant for an id. Raises ValueError if not loaded/unknown."""
    if variant_id not in _mentor_variants:
        raise ValueError(f"Unknown mentor variant: {variant_id!r}")
    return _mentor_variants[variant_id]


def get_variant(ability_id: str, variant_id: str) -> MentorVariant:
    """Return the variant identified by (ability_id, variant_id), fail-loud.

    The contracted accessor for the activation path (story-003): it validates the
    variant exists AND belongs to the named base ability, so a stored active
    variant id that doesn't match the ability fails loud rather than overriding
    the wrong technique.
    """
    variant = get_mentor_variant(variant_id)
    if variant.ability_id != ability_id:
        raise ValueError(f"Mentor variant {variant_id!r} belongs to {variant.ability_id!r}, not {ability_id!r}")
    return variant


def get_variants_for_ability(ability_id: str) -> tuple[MentorVariant, ...]:
    """Return all loaded variants for a base ability, in load order.

    Empty tuple when the ability has none loaded (e.g. an unknown id), the
    ability-keyed analogue of spells.get_spells_by_source.
    """
    return tuple(v for v in _mentor_variants.values() if v.ability_id == ability_id)


def is_loaded() -> bool:
    """True once the variants have been populated (startup load or test seam)."""
    return bool(_mentor_variants)


async def load_mentor_variants() -> None:
    """Load the mentor variant catalog from the DB into _mentor_variants.

    Called at agent + async-worker startup beside load_spells(). Fails loud if the
    query or a row errors. Builds a local dict then swaps in one synchronous step
    (no await between), so a malformed row fails loud WITHOUT wiping an
    already-loaded map and a concurrent get_variant never observes a
    half-populated map.
    """
    import db

    pool = await db.get_pool()
    rows = await pool.fetch("SELECT id, data FROM mentor_variants")
    loaded: dict[str, MentorVariant] = {}
    for row in rows:
        data = json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]
        loaded[row["id"]] = parse_mentor_variant_row(row["id"], data)
    _mentor_variants.clear()
    _mentor_variants.update(loaded)
    logger.info("Loaded %d mentor variants", len(_mentor_variants))
