"""Common metadata for reactions granted by archetypes and spell libraries."""

from dataclasses import dataclass

import abilities
import spells

SPELL_TWINS = {
    "arcane_shield_spell": frozenset({"mage_shield_spell"}),
    "primal_bark_skin": frozenset({"druid_bark_skin", "warden_bark_skin"}),
}


@dataclass(frozen=True)
class Reaction:
    id: str
    name: str
    narration_cue: str
    window: abilities.ReactionWindow
    spell: spells.Spell | None = None


def get_reaction(reaction_id: str) -> Reaction:
    try:
        spell = spells.get_spell(reaction_id)
    except ValueError:
        ability = abilities.get_ability(reaction_id)
        if ability.window is None:
            raise ValueError(f"{reaction_id!r} is not a reaction") from None
        return Reaction(ability.id, ability.name, ability.narration_cue, ability.window)
    if spell.reaction_window is None:
        raise ValueError(f"{reaction_id!r} is not a reaction")
    return Reaction(spell.id, spell.name, spell.narration_cue, spell.reaction_window, spell)
