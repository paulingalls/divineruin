from collections.abc import Iterable

import abilities


def validate_spell_source(magic_source: str | None, spell_source: str) -> None:
    if magic_source == spell_source or magic_source == "cross":
        return

    holder_source = magic_source or "no magic source"
    raise ValueError(f"Cannot learn {spell_source} spell with {holder_source}.")


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
