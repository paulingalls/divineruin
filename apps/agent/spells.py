"""Spell catalog — DB-loaded content config (M8 / M3.3 / story-001).

content/spells.json is the single source of truth for the FULL 87-spell casting
catalog, keyed by magic source (arcane/divine/primal). M3.3 (decision
spell-catalog-full-casting-ssot) made this the casting-data SSOT, superseding the
earlier elective-only seam (235ae150c5d3): cast_spell/get_spell_info need data for
every castable spell, so the caster CORE spells (Arcane Bolt, Sacred Flame, Heal
Wounds, Thorn Whip, Healing Touch) now live here too. archetype_abilities `core`
rows are the ACCESS grant (which spells an archetype always-knows) + per-archetype
description and narration; their Focus cost — the one cast number shared with the
cast path — is NOT authored there but composed from this catalog at load time
(abilities._resolve_cost via spell_id, Try 2), so it can't drift. This module is the Python loader, an exact mirror
of abilities.py: a module-global dict populated by load_spells() at process startup
(or set_spells() in tests), a fail-loud parse_spell_row shared by the DB loader and
the JSON test fixture, and sync accessors.

The catalog is SOURCE-keyed, not archetype-keyed: get_spells_by_source filters by
the magic source, the analogue of abilities.get_archetype_abilities. The row shape
carries the full M3.3 cast-time schema (resonance_by_source, terrain_effects,
audio_cue, concentration); parse_spell_row is STRICT on these
(decision spell-loader-strict-contract) while still ignoring genuinely-unknown extra
fields for forward compatibility. Downstream stories consume get_spell /
get_spells_by_source: character_spells (story-002), learn(spell,id) (story-005),
preparation (story-006).
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Literal, get_args

from catalog_parse import parse_int, parse_int_dict, parse_str

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
    focus_cost: int
    mechanics: str
    narration_cue: str
    # M3.3 cast-time fields. Defaults keep in-code Spell(...) builds (tests/fixtures)
    # working without supplying them; parse_spell_row REQUIRES them in raw rows (strict,
    # decision spell-loader-strict-contract). resonance_by_source maps the spell's magic
    # source to its catalog Resonance value (magic.md Spell-to-Resonance Map); terrain_effects
    # holds the Primal terrain->Resonance overrides ({} for non-Primal); audio_cue is the SFX
    # code auto-pushed on cast ("" if silent); concentration gates M3.4. (The catalog "Level"
    # column / per-row level_requirement was deleted in story-008: orphaned non-gating metadata
    # with no reader — access is gated by the per-archetype tier tables, not per-spell level.)
    resonance_by_source: dict[str, int] = field(default_factory=dict)
    terrain_effects: dict[str, int] = field(default_factory=dict)
    audio_cue: str = ""
    concentration: bool = False


# Module-level runtime-loaded spells, keyed by spell id. Populated by load_spells()
# at startup, or by set_spells() in tests.
_spells: dict[str, Spell] = {}


def parse_spell_row(spell_id: str, data: dict) -> Spell:
    """Parse a raw dict (from JSON file or DB JSONB) into a Spell.

    Shared by load_spells (DB) and the JSON test fixture. Raises ValueError wrapping
    the underlying error with the row id for context; owns fail-loud validation of the
    source/spell_tier enums and the typed fields.

    STRICT on the four known M3.3 fields (resonance_by_source, terrain_effects, audio_cue,
    concentration) — a missing or malformed one fails loud naming the
    row (decision spell-loader-strict-contract). Genuinely-unknown extra fields are still
    ignored, so the loader stays forward-compatible for future schema additions. Generic
    field validation reuses the shared catalog_parse primitives.
    """
    try:
        source = data["source"]
        if source not in _SPELL_SOURCES:
            raise ValueError(f"spell {spell_id!r} source {source!r} not in {sorted(_SPELL_SOURCES)}")
        spell_tier = data["spell_tier"]
        if spell_tier not in _SPELL_TIERS:
            raise ValueError(f"spell {spell_id!r} spell_tier {spell_tier!r} not in {sorted(_SPELL_TIERS)}")
        concentration = data["concentration"]
        if not isinstance(concentration, bool):
            raise ValueError(f"spell {spell_id!r} concentration is not a bool")
        return Spell(
            id=spell_id,
            name=data["name"],
            source=source,
            spell_tier=spell_tier,
            focus_cost=parse_int(data["focus_cost"], f"spell {spell_id!r} focus_cost"),
            mechanics=data["mechanics"],
            narration_cue=data["narration_cue"],
            resonance_by_source=parse_int_dict(data["resonance_by_source"], f"spell {spell_id!r} resonance_by_source"),
            terrain_effects=parse_int_dict(data["terrain_effects"], f"spell {spell_id!r} terrain_effects"),
            audio_cue=parse_str(data["audio_cue"], f"spell {spell_id!r} audio_cue"),
            concentration=concentration,
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
    filter further by spell_tier (the source-keyed analogue of
    abilities.get_archetype_abilities). The level->tier unlock gate lives in
    leveling.is_spell_tier_unlocked, keyed by (archetype, tier) — spells carry no
    per-row level, and the unlock floor varies by the caster's archetype.
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
