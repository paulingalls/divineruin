"""Spell catalog — DB-loaded content config (M8 / story-001).

content/spells.json is the single source of truth for the ELECTIVE spell library:
the learnable pool keyed by magic source (arcane/divine/primal). Caster CORE spells
are NOT here — they stay archetype_abilities rows with ability_type=core (the
M2.2/M2.4 seam, decision 235ae150c5d3). This module is the Python loader, an exact
mirror of abilities.py: a module-global dict populated by load_spells() at process
startup (or set_spells() in tests), a fail-loud parse_spell_row shared by the DB
loader and the JSON test fixture, and sync accessors.

The catalog is SOURCE-keyed, not archetype-keyed: get_spells_by_source filters by
the magic source, the analogue of abilities.get_archetype_abilities. The row shape
borrows Phase-3 Magic's M3.3 schema minimally and is forward-compatible — extra
fields (resonance_by_source, terrain_effects, ...) in the JSONB column are ignored
here and consumed by M3.3 when it ships. Downstream stories consume get_spell /
get_spells_by_source: character_spells (story-002), learn(spell,id) (story-005),
preparation (story-006).
"""

import json
import logging
from dataclasses import dataclass
from typing import Literal, get_args

logger = logging.getLogger("divineruin.spells")

SpellSource = Literal["arcane", "divine", "primal"]
SpellTier = Literal["cantrip", "minor", "standard", "major", "supreme"]

# Closed vocabularies — the loader owns fail-loud validation, mirroring
# abilities.parse_ability_row's ability_type guard.
_SPELL_SOURCES = frozenset(get_args(SpellSource))
_SPELL_TIERS = frozenset(get_args(SpellTier))


@dataclass(frozen=True)
class Spell:
    id: str
    name: str
    source: SpellSource
    spell_tier: SpellTier
    level_requirement: int
    focus_cost: int
    mechanics: str
    narration_cue: str


# Module-level runtime-loaded spells, keyed by spell id. Populated by load_spells()
# at startup, or by set_spells() in tests.
_spells: dict[str, Spell] = {}


def _require_int(data: dict, key: str, spell_id: str) -> int:
    value = data[key]
    # bool is a subclass of int — exclude it explicitly (parity with the TS loader's
    # integer guard, so a shared row fails identically on both sides).
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"spell {spell_id!r} {key} is not an int")
    return value


def parse_spell_row(spell_id: str, data: dict) -> Spell:
    """Parse a raw dict (from JSON file or DB JSONB) into a Spell.

    Shared by load_spells (DB) and the JSON test fixture. Raises ValueError wrapping
    the underlying error with the row id for context; owns fail-loud validation of the
    source/spell_tier enums and the integer fields.
    """
    try:
        source = data["source"]
        if source not in _SPELL_SOURCES:
            raise ValueError(f"spell {spell_id!r} source {source!r} not in {sorted(_SPELL_SOURCES)}")
        spell_tier = data["spell_tier"]
        if spell_tier not in _SPELL_TIERS:
            raise ValueError(f"spell {spell_id!r} spell_tier {spell_tier!r} not in {sorted(_SPELL_TIERS)}")
        return Spell(
            id=spell_id,
            name=data["name"],
            source=source,
            spell_tier=spell_tier,
            level_requirement=_require_int(data, "level_requirement", spell_id),
            focus_cost=_require_int(data, "focus_cost", spell_id),
            mechanics=data["mechanics"],
            narration_cue=data["narration_cue"],
        )
    except (KeyError, TypeError) as e:
        raise ValueError(f"Malformed spells row {spell_id!r}: {e}") from e


def set_spells(config: dict[str, Spell]) -> None:
    """Test seam: populate _spells directly without going through the DB."""
    _spells.clear()
    _spells.update(config)


def get_spell(spell_id: str) -> Spell:
    """Return the spell for an id. Raises ValueError if not loaded/unknown."""
    if spell_id not in _spells:
        raise ValueError(f"Unknown spell: {spell_id!r}")
    return _spells[spell_id]


def get_spells_by_source(source: str) -> tuple[Spell, ...]:
    """Return all loaded spells for a magic source, in load order.

    Empty tuple when the source has none loaded (e.g. an unknown source). Callers
    filter further by spell_tier / level_requirement (the source-keyed analogue of
    abilities.get_archetype_abilities).
    """
    return tuple(s for s in _spells.values() if s.source == source)


def is_loaded() -> bool:
    """True once the spells have been populated (startup load or test seam)."""
    return bool(_spells)


async def load_spells() -> None:
    """Load the spell catalog from the DB into _spells.

    Called at agent + async-worker startup beside load_abilities(). Fails loud if the
    query or a row errors. Builds a local dict then swaps in one synchronous step (no
    await between), so a malformed row fails loud WITHOUT wiping an already-loaded map
    and a concurrent get_spell never observes a half-populated map.
    """
    import db

    pool = await db.get_pool()
    rows = await pool.fetch("SELECT id, data FROM spells")
    loaded: dict[str, Spell] = {}
    for row in rows:
        data = json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]
        loaded[row["id"]] = parse_spell_row(row["id"], data)
    _spells.clear()
    _spells.update(loaded)
    logger.info("Loaded %d spells", len(_spells))
