"""Spell preparation rules — Track 3, on long rest (M8 story-006). Zero IO, no async.

Preparation is a deterministic Resolve (Golden Rule 3; ADR 0007: no new @function_tool).
These pure gates enforce the Track 3 rules (game_mechanics_archetypes.md L1255-1283); the
async long-rest wiring that calls them lives in rest_mechanics.prepare_spells_on_long_rest.

Both gates fail loud: they raise ValueError with a specific message on violation and
return None when the preparation is allowed (mirrors rest_mechanics.swap_elective_on_long_rest).
"""

from typing import get_args

import leveling
from spells import SpellTier

# Primal casters may only CHANGE preparation in natural terrain — they must commune with
# the land (Druid lore). This is exactly the set of primal-source casters.
PRIMAL_TERRAIN_CASTERS = frozenset({"druid", "beastcaller", "warden"})

# These archetypes cap at Major tier — no Supreme access (spec L803/L1060/L1135). They are
# a STRICT SUBSET of divine casters (cleric/oracle keep Supreme), so the cap is an explicit
# id set, not magic_source — consistent with story-003's "explicit set, not magic_source".
MAJOR_TIER_CAPPED_ARCHETYPES = frozenset({"paladin", "diplomat", "marshal"})

# Canonical low->high tier ordering, derived from the SpellTier Literal so there is a single
# source of truth (the Literal members are ordered). Used for the Major-cap comparison.
SPELL_TIER_ORDER = get_args(SpellTier)
_MAJOR_RANK = SPELL_TIER_ORDER.index("major")


def can_change_preparation(archetype_id: str, *, in_natural_terrain: bool) -> None:
    """Operation-level gate: may this archetype change its preparation here?

    Primal casters (Druid/Beastcaller/Warden) can only re-prepare in natural terrain.
    All other archetypes re-prepare anywhere. Raises ValueError when blocked.
    """
    if archetype_id in PRIMAL_TERRAIN_CASTERS and not in_natural_terrain:
        raise ValueError(f"{archetype_id!r} is a primal caster and can only change preparation in natural terrain")


def can_prepare(
    *,
    spell_id: str,
    spell_tier: SpellTier,
    archetype_id: str,
    character_level: int,
    known_spell_ids: frozenset[str] | set[str],
    prepared_elective_count: int,
    slot_limit: int,
) -> None:
    """Per-spell gate: may this character prepare this elective spell into a slot?

    Enforces, in order: must know the spell, must have level access to its tier, the
    Major-tier cap for capped archetypes, and an open elective slot. Raises ValueError
    with a specific message on the first violated rule; returns None when allowed.

    `prepared_elective_count` counts only ELECTIVE prepared spells — core spells are
    archetype_abilities (a different table), always prepared and slot-free, never counted.
    """
    if spell_id not in known_spell_ids:
        raise ValueError(f"character does not know {spell_id!r}; cannot prepare an unknown spell")

    # Level->tier gate (fails loud on an unknown tier — see leveling.is_spell_tier_unlocked).
    if not leveling.is_spell_tier_unlocked(spell_tier, character_level):
        min_level = leveling.MIN_LEVEL_BY_SPELL_TIER[spell_tier]
        raise ValueError(
            f"cannot prepare {spell_id!r}: {spell_tier} spells unlock at level {min_level}, "
            f"character is level {character_level}"
        )

    if archetype_id in MAJOR_TIER_CAPPED_ARCHETYPES and SPELL_TIER_ORDER.index(spell_tier) > _MAJOR_RANK:
        raise ValueError(f"{archetype_id!r} caps at Major tier and cannot prepare a {spell_tier} spell")

    if prepared_elective_count >= slot_limit:
        raise ValueError(f"no open elective slot: {prepared_elective_count} prepared, limit is {slot_limit}")
