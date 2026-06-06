"""Rest recovery — short/long rest resource restoration (pure), plus two long-rest
DB-backed operations: the elective technique swap and elective spell preparation.

apply_short_rest/apply_long_rest/apply_rest are pure resource-pool math. The long
rest additionally lets a character swap a known L4/L8 elective for an unchosen
option in the same pool (swap_elective_on_long_rest) without losing the old
technique, and choose which known elective spells fill their loadout
(prepare_spells_on_long_rest) — those two are async and mutate the DB.
"""

from typing import Literal

import asyncpg

import abilities
import ability_persistence
import archetypes
import character_spells
import spell_preparation
import spells

RestType = Literal["short", "long"]


def apply_short_rest(
    current_stamina: int,
    max_stamina: int,
    current_focus: int,
    max_focus: int,
) -> tuple[int, int]:
    """Short rest (~1 hour): stamina fully restored, focus recovers to half pool minimum."""
    new_stamina = max_stamina
    new_focus = max(current_focus, max_focus // 2)
    return new_stamina, new_focus


def apply_long_rest(
    current_stamina: int,
    max_stamina: int,
    current_focus: int,
    max_focus: int,
    current_hp: int,
    max_hp: int,
) -> tuple[int, int, int]:
    """Long rest (~8 hours): all resource pools fully restored."""
    return max_stamina, max_focus, max_hp


def apply_rest(
    rest_type: RestType,
    current_stamina: int,
    max_stamina: int,
    current_focus: int,
    max_focus: int,
    current_hp: int,
    max_hp: int,
) -> tuple[int, int, int]:
    """Dispatcher: apply short or long rest, returning (stamina, focus, hp)."""
    if rest_type == "short":
        stamina, focus = apply_short_rest(current_stamina, max_stamina, current_focus, max_focus)
        return stamina, focus, current_hp
    elif rest_type == "long":
        return apply_long_rest(
            current_stamina,
            max_stamina,
            current_focus,
            max_focus,
            current_hp,
            max_hp,
        )
    else:
        msg = f"Unknown rest type: {rest_type!r}"
        raise ValueError(msg)


async def swap_elective_on_long_rest(
    player_id: str,
    from_ability_id: str,
    to_ability_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
    abilities_mod=abilities,
    persistence_mod=ability_persistence,
) -> None:
    """On a long rest, swap a currently-equipped L4/L8 elective for an unchosen
    option in the same pool.

    Both abilities must be electives of the same archetype and level (i.e. the same
    L4 or L8 pool). The swapped-out technique's row is kept (set equipped=FALSE), so
    it stays re-selectable on a later rest. Raises ValueError on any validation
    failure (unknown id, non-elective, cross-pool, or a from-ability the character
    does not currently have equipped); makes no mutation in that case.

    This makes two writes (from->equipped=FALSE, to->equipped=TRUE). They are atomic
    ONLY if the caller passes a transactional ``conn`` (e.g. from ``db.transaction()``).
    With ``conn=None`` each write runs on a separate pooled connection, so a failure
    between them can leave the character with neither elective equipped — callers that
    mutate other state in the same long rest MUST wrap this in a transaction.
    """
    from_ability = abilities_mod.get_ability(from_ability_id)  # ValueError if unknown
    to_ability = abilities_mod.get_ability(to_ability_id)
    for ability in (from_ability, to_ability):
        if ability.ability_type != "elective":
            raise ValueError(f"{ability.id!r} is not an elective (ability_type={ability.ability_type!r})")
    if to_ability.archetype_id != from_ability.archetype_id:
        raise ValueError(
            f"Cannot swap across archetypes: {from_ability_id!r} is {from_ability.archetype_id}, "
            f"{to_ability_id!r} is {to_ability.archetype_id}"
        )
    if to_ability.level_requirement != from_ability.level_requirement:
        raise ValueError(
            f"Cannot swap across elective tiers: {from_ability_id!r} is L{from_ability.level_requirement}, "
            f"{to_ability_id!r} is L{to_ability.level_requirement}"
        )

    known = await persistence_mod.get_character_abilities(player_id, conn=conn)
    equipped_ids = {row["ability_id"] for row in known if row.get("equipped")}
    if from_ability_id not in equipped_ids:
        raise ValueError(f"Character {player_id!r} does not have {from_ability_id!r} equipped to swap out")

    # Keep the old technique's row (equipped=FALSE -> re-selectable); equip the new one.
    await persistence_mod.set_elective_equipped(player_id, from_ability_id, False, conn=conn)
    await persistence_mod.set_elective_equipped(player_id, to_ability_id, True, conn=conn)


async def prepare_spells_on_long_rest(
    player_id: str,
    loadout: list[str],
    *,
    slot_limit: int,
    archetype_id: str,
    character_level: int,
    in_natural_terrain: bool,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
    spells_mod=spells,
    character_spells_mod=character_spells,
    preparation_mod=spell_preparation,
    archetypes_mod=archetypes,
) -> None:
    """On a long rest, set the character's prepared elective spells to exactly ``loadout``.

    Track 3 preparation (game_mechanics_archetypes.md L1255-1283), a deterministic Resolve
    (ADR 0007: no new @function_tool). Enforces the rules via spell_preparation: a primal
    caster may only re-prepare in natural terrain, every loadout spell must be known, of an
    unlocked tier, within the archetype's tier cap, and the loadout must fit ``slot_limit``.

    The whole loadout is validated BEFORE any write, so an invalid or over-limit loadout is
    refused atomically (nothing persists). Core spells are archetype_abilities (a different
    table) — always prepared, slot-free, never read or touched here. ``loadout`` is the full
    desired set: electives currently prepared but absent from it are un-prepared.

    Writes (un-prepare + prepare) are atomic ONLY if the caller passes a transactional
    ``conn`` (e.g. from ``db.transaction()``); with ``conn=None`` each runs on a separate
    pooled connection, so a mid-flight failure can leave a partially-applied loadout.
    """
    # Operation-level gate first — a blocked primal caster makes no reads or writes.
    # magic_source is derived from the archetype chassis (SSOT) rather than a hardcoded set.
    magic_source = archetypes_mod.get_archetype_chassis(archetype_id).magic_source
    preparation_mod.can_change_preparation(magic_source, in_natural_terrain=in_natural_terrain)

    # A loadout is conceptually a set of distinct electives. Duplicates are malformed input:
    # they desync the slot accounting below (enumerate counts entries, not unique spells), so
    # fail loud before any read/write rather than silently mis-count or double-write.
    if len(set(loadout)) != len(loadout):
        raise ValueError(f"loadout has duplicate spell ids: {loadout!r}")

    known = await character_spells_mod.get_known(player_id, conn=conn)
    known_ids = {row["spell_id"] for row in known}

    # Validate the entire loadout up front (all-or-nothing). The slot count is the number of
    # spells already accepted, so a loadout longer than slot_limit is refused on its last entry.
    for accepted_count, spell_id in enumerate(loadout):
        spell = spells_mod.get_spell(spell_id)  # ValueError on an unknown catalog id
        preparation_mod.can_prepare(
            spell_id=spell_id,
            spell_tier=spell.spell_tier,
            archetype_id=archetype_id,
            character_level=character_level,
            known_spell_ids=known_ids,
            prepared_elective_count=accepted_count,
            slot_limit=slot_limit,
        )

    # Write only the delta: un-prepare electives dropped from the loadout, prepare the ones
    # newly added. A spell already prepared and still in the loadout needs no write.
    loadout_set = set(loadout)
    currently_prepared = {row["spell_id"] for row in known if row["is_prepared"]}
    for spell_id in currently_prepared - loadout_set:
        await character_spells_mod.set_prepared(player_id, spell_id, False, conn=conn)
    for spell_id in loadout_set - currently_prepared:
        await character_spells_mod.set_prepared(player_id, spell_id, True, conn=conn)
