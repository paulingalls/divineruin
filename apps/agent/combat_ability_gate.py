from __future__ import annotations

import abilities
import mentor_variants
from mentor_variants import MentorVariant

DeclaredAbility = tuple[abilities.Ability, MentorVariant | None]


def declared_ability(action: str | None) -> DeclaredAbility | None:
    if action is None:
        return None
    try:
        return abilities.get_ability(action), None
    except ValueError:
        pass
    try:
        variant = mentor_variants.get_mentor_variant(action)
    except ValueError:
        return None
    return abilities.get_ability(variant.ability_id), variant
