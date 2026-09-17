from collections.abc import Iterable

import abilities


def validate_spell_source(magic_source: str | None, spell_source: str) -> None:
    if magic_source == spell_source or magic_source == "cross":
        return

    holder = f"{magic_source} magic" if magic_source else "an archetype with no magic source"
    raise ValueError(f"{spell_source} spells cannot be held by {holder}")


def castable_spell_ids(archetype_id: str | None, library_ids: Iterable[str]) -> frozenset[str]:
    core_ids = (
        {
            ability.spell_id
            for ability in abilities.get_archetype_abilities(archetype_id)
            if ability.ability_type == "core" and ability.spell_id
        }
        if archetype_id
        else set()
    )
    return frozenset(core_ids | set(library_ids))
