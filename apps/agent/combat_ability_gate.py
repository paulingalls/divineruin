from __future__ import annotations

import abilities
from mentor_variants import MentorVariant

DeclaredAbility = tuple[abilities.Ability, MentorVariant | None]


def declared_ability(action: str | None) -> DeclaredAbility | None:
    if action is None:
        return None
    try:
        return abilities.get_ability(action), None
    except ValueError:
        return None
