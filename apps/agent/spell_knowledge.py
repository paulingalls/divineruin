from collections.abc import Iterable

import abilities


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
