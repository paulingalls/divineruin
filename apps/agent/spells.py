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
from typing import TYPE_CHECKING, Literal, get_args

import conditions
from catalog_parse import parse_int, parse_int_dict, parse_str

if TYPE_CHECKING:
    from abilities import Ability  # type-only: abilities.py imports spells, so never import at runtime

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
    # holds the Primal terrain->Resonance overrides ({} for non-Primal); audio_cue is a free-text
    # DM audio-direction cue voiced/directed on cast (returned in the cast packet, spell_casting.py)
    # — NOT a literal client SFX code, nothing maps it to real SFX yet; codes like "CMB-008" are
    # shorthand within that free text. Required + non-empty per row (test_spells_content guards it,
    # concern e3af222251df); concentration gates M3.4. (The catalog "Level"
    # column / per-row level_requirement was deleted in story-008: orphaned non-gating metadata
    # with no reader — access is gated by the per-archetype tier tables, not per-spell level.)
    resonance_by_source: dict[str, int] = field(default_factory=dict)
    terrain_effects: dict[str, int] = field(default_factory=dict)
    audio_cue: str = ""
    concentration: bool = False
    # M4.8 story-004: the beneficial condition this spell PRODUCES on its target (e.g. "blessed"),
    # or None for a spell that applies no condition. Optional + forward-compatible: existing rows
    # omit it. When present, parse_spell_row fail-louds an unknown type against CONDITION_CATALOG.
    applies_condition: str | None = None
    # M4.8 story-007: the maximum number of targets a multi-target spell may name (e.g. Bless = 3),
    # or None for an unbounded/single-target spell. Optional + forward-compatible. validate_target_count
    # is the single cap SSOT enforced at both the OOC cast and (story-012) the in-combat declaration.
    max_targets: int | None = None


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
        # Optional producer field (M4.8 story-004): when present it must name a real condition type,
        # so a typo fails at load (strict-loader convention) instead of silently producing nothing.
        applies_condition = data.get("applies_condition")
        if applies_condition is not None:
            conditions.assert_known_condition(applies_condition, f"spell {spell_id!r}")
        # Optional multi-target cap (M4.8 story-007): when present it must be a positive int (bool is
        # not an int here — reject it), so a typo/0 fails at load instead of silently uncapping.
        max_targets = data.get("max_targets")
        if max_targets is not None and (
            isinstance(max_targets, bool) or not isinstance(max_targets, int) or max_targets < 1
        ):
            raise ValueError(f"spell {spell_id!r} max_targets {max_targets!r} must be a positive int")
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
            applies_condition=applies_condition,
            max_targets=max_targets,
        )
    except (KeyError, TypeError) as e:
        raise ValueError(f"Malformed spells row {spell_id!r}: {e}") from e


def validate_target_count(spell: "Spell | Ability", target_ids: list[str]) -> None:
    """Fail loud when a multi-target cast names more allies than the spell/ability allows (M4.8
    story-007; widened to abilities in story-016 — both carry .id/.name/.max_targets).

    The single cap SSOT: no-op when the action has no ``max_targets`` (unbounded/single-target).
    Raises ValueError (callers at the tool boundary convert to a DM-narratable ToolError) so an
    over-cap cast is rejected before any resource write. Reused unchanged by the in-combat path
    (story-012)."""
    if spell.max_targets is not None and len(target_ids) > spell.max_targets:
        raise ValueError(f"spell {spell.id!r} targets at most {spell.max_targets} (got {len(target_ids)})")


def normalize_target_list(spell: "Spell | Ability", target_id: str | None, target_ids: list[str]) -> list[str]:
    """Normalize + validate a multi-target cast's ally list (M4.8 story-007) — the targeting SSOT.
    Accepts a Spell OR a condition-applying Ability (story-016): both expose .id/.name/.max_targets.

    Order, all BEFORE any resource write: reject ambiguous both-args -> order-preserving dedup ->
    reject empty -> reject a spell with no ``max_targets`` (single-target only; this also closes the
    revival Hollow-gate bypass) -> enforce the cap. Raises ValueError (the tool boundary converts to a
    DM-narratable ToolError) so an invalid cast is refused before Focus/Resonance is touched. Returns
    the deduped list to apply."""
    if target_id is not None:
        raise ValueError("pass target_id OR target_ids, not both")
    deduped = list(dict.fromkeys(target_ids))
    if not deduped:
        raise ValueError("name at least one ally")
    if spell.max_targets is None:
        raise ValueError(f"{spell.name} does not support multiple targets")
    validate_target_count(spell, deduped)
    return deduped


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
