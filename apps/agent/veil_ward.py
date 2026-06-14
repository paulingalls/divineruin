"""Veil Ward rules engine (story-002, M3.2) — pure, no IO.

A Veil Ward locally reinforces the Veil so a caster can push harder with less danger.
While a ward is active it halves the Resonance a cast generates (round down), grants
+4 to Hollow Echo rolls, and dampens spells by -1 damage die and -1 DC. Like the
Resonance and Hollow Echo engines this is a deterministic closed-table mechanic
(CLAUDE.md golden rule #3): the modifier values and the per-archetype ward-source
costs are code constants, not DB-loaded content (same call as resonance.py).

This module owns the ward's pure effects and its source table. The persisted ward
state lives in db_mutations_veil_ward (players.data JSONB) and the in-memory
VeilWardState lives on SessionData; the activation tool (story-003) and the cast-time
halving (story-004) compose these primitives.

Spec source: docs/game_mechanics/game_mechanics_magic.md §Veil Ward (189-217):
generation halved (round down), +4 echo, -1 damage die, -1 DC; sources Cleric L7 4F /
Druid L9 5F (natural terrain only) / Paladin L10 3F+3S, plus Artificer item and Sacred
sites. M3.2 scopes WARD_SOURCES to the Focus/Stamina caster sources; the Artificer item
and Sacred-site passive sources are deferred.
"""

from dataclasses import dataclass

# Ward combat modifiers (spec 195-200), uniform across every ward source. Consumed by
# the cast path (story-004): generation is halved, the Hollow Echo roll gets +4, and
# spell damage/DC drop by one each while the ward is active.
WARD_ECHO_BONUS = 4
WARD_DAMAGE_DIE_PENALTY = -1
WARD_DC_PENALTY = -1


@dataclass(frozen=True)
class WardSource:
    """The level + resource cost at which an archetype can raise a Veil Ward."""

    min_level: int
    focus: int
    stamina: int = 0


# Archetype id -> ward source (spec 204-210). Only the enforceable cost fields are
# modeled: Druid's "natural terrain only" restriction is NOT a column because no runtime
# location->terrain map exists yet (an unenforced flag would be forward-wired dead state).
# story-003 gates level + Focus/Stamina from this table; the Druid terrain gate and the
# Artificer-item / Sacred-site (passive world entity) sources are deferred past M3.2.
WARD_SOURCES: dict[str, WardSource] = {
    "cleric": WardSource(min_level=7, focus=4),
    "druid": WardSource(min_level=9, focus=5),
    "paladin": WardSource(min_level=10, focus=3, stamina=3),
}


def halve_generation(generated: int) -> int:
    """Halve the Resonance a cast generates while a Veil Ward is active (round down, spec 197).

    Fails loud on a negative input — generation is always non-negative (cantrips are 0).
    """
    if generated < 0:
        raise ValueError(f"generated must be non-negative, got {generated}")
    return generated // 2
