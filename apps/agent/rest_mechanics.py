"""Rest recovery — short/long rest resource restoration (pure), plus the long-rest
elective swap (async, DB-backed).

apply_short_rest/apply_long_rest/apply_rest are pure resource-pool math. The long
rest additionally lets a character swap a known L4/L8 elective for an unchosen
option in the same pool (swap_elective_on_long_rest) without losing the old
technique — that one function is async and mutates character_abilities.
"""

from typing import Literal

import asyncpg

import abilities
import ability_persistence

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
