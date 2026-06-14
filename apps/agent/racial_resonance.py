"""Racial Resonance bonus table — DB-loaded content config (M3.4 / story-001).

content/racial_resonance_bonuses.json is the single source of truth for the six races'
mechanically distinct relationships with Resonance (spec game_mechanics_magic.md §Racial
Resonance Integration, 221-293). Per the Phase-3 audit guidance the racial layer lives in
its OWN seeded table, decoupled from creation_races.RaceData — so RaceData stays lean and
the racial mechanics evolve as content, not as a widened race schema.

This module is the FOUNDATION the other M3.4 racial stories read: rather than hardcode the
modifier values, story-003 (resonance.py Korath/Thessyn params), story-004 (hollow_echo.py
Vaelti advantage), story-005 (Draethar Inner Fire tool) and story-006 (the cast keystone)
call get_racial_resonance_modifier. The pure engines (resonance.py, hollow_echo.py) stay
pure and take plain int/bool params; only the call sites read this lookup.

The table is HETEROGENEOUS — each race carries only its own modifier keys, stored in the
exact param shapes the downstream engines expect, so a call site forwards the looked-up
value verbatim (human decay_bonus=1 -> apply_resonance_decay racial_modifier=1; vaelti
echo_save_advantage=True -> resolve_hollow_echo advantage=True; draethar 3 / "1d6").
get_racial_resonance_modifier FAILS LOUD on an unknown race or an unknown modifier_type for
that race (never a silent default) — call sites guard by race, so the strictness is safe and
surfaces a wiring defect immediately (fail-fast, fail-loud).

Exact mirror of the spells.py loader: a module-global dict populated by load_racial_resonance()
at startup (or set_racial_bonuses() in tests), a fail-loud parse_racial_resonance_row shared by
the DB loader and the JSON test fixture, and sync accessors. parse_racial_resonance_row is
STRICT on the per-race modifier contract (_EXPECTED_MODIFIERS): every race must be known and
carry exactly its expected modifier keys, each of its expected value type (decision
spell-loader-strict-contract).
"""

import json
import logging
from dataclasses import dataclass

from catalog_parse import parse_dict, parse_int, parse_str

logger = logging.getLogger("divineruin.racial_resonance")

# Per-race modifier contract: race id -> {modifier_type -> expected value type}. This is the
# closed spec table (magic.md 221-293); the content rows and load boundary are validated
# against it. Values are stored as the additive params downstream engines consume. Only the
# human consumer exists on the current engine; the rest are params the named story ADDS (the
# signatures below are forward references, not today's interface):
#   human decay_bonus      -> apply_resonance_decay(racial_modifier=) : +1 => decay 2/round (exists)
#   korath primal_reduction-> story-003 primal-reduction helper       : subtract from generation
#   thessyn flickering_..  -> story-003 ADDS get_resonance_state(flickering_bonus=) : band 5-8 -> 6-9
#   vaelti echo_save_advantage -> story-004 ADDS resolve_hollow_echo(advantage=)    : best-of-two save
#   draethar inner_fire_*  -> story-005 Inner Fire tool               : -3 Resonance, "1d6" self fire
#   elari veil_sense / resonance_arcana_bonus -> passive sensing narration (no cast consumer yet)
_EXPECTED_MODIFIERS: dict[str, dict[str, type]] = {
    "human": {"decay_bonus": int},
    "korath": {"primal_reduction": int},
    "thessyn": {"flickering_threshold_bonus": int},
    "vaelti": {"echo_save_advantage": bool},
    "draethar": {"inner_fire_resonance_reduction": int, "inner_fire_self_damage": str},
    "elari": {"veil_sense": bool, "resonance_arcana_bonus": int},
}


@dataclass(frozen=True)
class RacialResonance:
    """One race's Resonance modifier set. ``race`` is the row id; ``modifiers`` is the
    validated heterogeneous map (int/bool/str values) per _EXPECTED_MODIFIERS."""

    race: str
    name: str
    modifiers: dict[str, object]


# Module-level runtime-loaded bonuses, keyed by race id. Populated by load_racial_resonance()
# at startup, or by set_racial_bonuses() in tests.
_bonuses: dict[str, RacialResonance] = {}


def _validate_modifier_value(value: object, expected: type, ctx: str) -> object:
    """Validate one modifier value against its expected type; fail loud naming the field.

    Delegates int/str to the shared catalog_parse primitives (which already exclude bool
    from int, parity with the TS guard); bool has no primitive, so it's guarded inline.
    """
    if expected is int:
        return parse_int(value, ctx)
    if expected is str:
        return parse_str(value, ctx)
    if expected is bool and not isinstance(value, bool):
        raise ValueError(f"{ctx} is not a bool")
    return value


def parse_racial_resonance_row(race_id: str, data: dict) -> RacialResonance:
    """Parse a raw dict (from JSON file or DB JSONB) into a RacialResonance.

    Shared by load_racial_resonance (DB) and the JSON test fixture. Raises ValueError
    wrapping the underlying error with the race id for context. STRICT on the per-race
    contract: the race must be known, and its modifiers must be exactly the expected keys,
    each of its expected value type (decision spell-loader-strict-contract).
    """
    try:
        if race_id not in _EXPECTED_MODIFIERS:
            raise ValueError(f"race {race_id!r} not in {sorted(_EXPECTED_MODIFIERS)}")
        name = parse_str(data["name"], f"race {race_id!r} name")
        modifiers = parse_dict(data["modifiers"], f"race {race_id!r} modifiers")
        expected = _EXPECTED_MODIFIERS[race_id]
        if modifiers.keys() != expected.keys():
            raise ValueError(f"race {race_id!r} modifiers {sorted(modifiers)} != expected {sorted(expected)}")
        validated = {
            key: _validate_modifier_value(modifiers[key], typ, f"race {race_id!r} modifier {key!r}")
            for key, typ in expected.items()
        }
        return RacialResonance(race=race_id, name=name, modifiers=validated)
    except (KeyError, TypeError) as e:
        raise ValueError(f"Malformed racial_resonance row {race_id!r}: {e}") from e


def set_racial_bonuses(config: dict[str, RacialResonance]) -> None:
    """Test seam: populate _bonuses directly without going through the DB."""
    _bonuses.clear()
    _bonuses.update(config)


def get_racial_resonance_modifier(race: str, modifier_type: str) -> object:
    """Return a race's modifier value (int | bool | str) for a modifier_type.

    Fails loud on an unknown race or an unknown modifier_type for that race — never a silent
    default. Call sites guard by race (e.g. cast_spell only reads primal_reduction for a
    Korath), so a raise here means a real wiring defect.
    """
    if race not in _bonuses:
        raise ValueError(f"Unknown race: {race!r}")
    modifiers = _bonuses[race].modifiers
    if modifier_type not in modifiers:
        raise ValueError(f"race {race!r} has no modifier {modifier_type!r}")
    return modifiers[modifier_type]


def is_loaded() -> bool:
    """True once the bonuses have been populated (startup load or test seam)."""
    return bool(_bonuses)


async def load_racial_resonance() -> None:
    """Load the racial Resonance bonus table from the DB into _bonuses.

    Called at agent + async-worker startup beside load_spells()/load_abilities(). Fails loud
    if the query or a row errors. Builds a local dict then swaps in one synchronous step (no
    await between), so a malformed row fails loud WITHOUT wiping an already-loaded map and a
    concurrent get_racial_resonance_modifier never observes a half-populated map.
    """
    import db

    pool = await db.get_pool()
    rows = await pool.fetch("SELECT id, data FROM racial_resonance_bonuses")
    loaded: dict[str, RacialResonance] = {}
    for row in rows:
        data = json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]
        loaded[row["id"]] = parse_racial_resonance_row(row["id"], data)
    _bonuses.clear()
    _bonuses.update(loaded)
    logger.info("Loaded %d racial resonance bonuses", len(_bonuses))
