"""Spell preparation rules — Track 3, on long rest (M8 story-006). Zero IO, no async.

Preparation is a deterministic Resolve (Golden Rule 3; ADR 0007: no new @function_tool).
These pure gates enforce the Track 3 rules (game_mechanics_archetypes.md L1255-1283); the
async long-rest wiring that calls them lives in rest_mechanics.prepare_spells_on_long_rest.

Both gates fail loud: they raise ValueError with a specific message on violation and
return None when the preparation is allowed (mirrors rest_mechanics.swap_elective_on_long_rest).
"""

import leveling
from spells import SpellTier

# The Major-tier cap for paladin/diplomat/marshal (no Supreme access, spec L809/L1060/L1135)
# is now subsumed by the per-archetype gate in leveling.MIN_LEVEL_BY_ARCHETYPE_TIER: those
# archetypes simply have no "supreme" entry, so is_spell_tier_unlocked returns False for it
# at any level — no separate cap set is needed (story-008, closes 66fa8bae).


def can_change_preparation(magic_source: str | None, *, in_natural_terrain: bool) -> None:
    """Operation-level gate: may a caster of this magic source change preparation here?

    Primal casters can only re-prepare in natural terrain — they must commune with the land
    (Druid lore). Every other source (arcane/divine/cross) and pure martials (None) re-prepare
    anywhere. Keyed on magic_source (the chassis SSOT), not an archetype-id set. Raises on block.
    """
    if magic_source == "primal" and not in_natural_terrain:
        raise ValueError("primal casters can only change preparation in natural terrain")


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

    Enforces, in order: must know the spell, the per-archetype level→tier access gate
    (which also enforces the Major cap for paladin/diplomat/marshal — they have no Supreme
    entry), and an open elective slot. Raises ValueError with a specific message on the
    first violated rule; returns None when allowed.

    `prepared_elective_count` counts only ELECTIVE prepared spells — core spells are
    archetype_abilities (a different table), always prepared and slot-free, never counted.
    """
    if spell_id not in known_spell_ids:
        raise ValueError(f"character does not know {spell_id!r}; cannot prepare an unknown spell")

    # Per-archetype level->tier gate (fails loud on an unknown tier/archetype — see
    # leveling.is_spell_tier_unlocked). A tier this archetype can never reach (e.g. paladin
    # Supreme) has no floor; a too-low character is below the archetype's floor.
    if not leveling.is_spell_tier_unlocked(archetype_id, spell_tier, character_level):
        floor = leveling.min_level_for_tier(archetype_id, spell_tier)
        if floor is None:
            raise ValueError(f"cannot prepare {spell_id!r}: {spell_tier} spells are not available to {archetype_id!r}")
        raise ValueError(
            f"cannot prepare {spell_id!r}: {spell_tier} spells unlock at level {floor} for "
            f"{archetype_id!r}, character is level {character_level}"
        )

    if prepared_elective_count >= slot_limit:
        raise ValueError(f"no open elective slot: {prepared_elective_count} prepared, limit is {slot_limit}")
