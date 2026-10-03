"""Harmonic Shield changes the effective declaration before the single real cast."""

from dataclasses import replace

import check_resolution_save
import spells
from choir_effects import suppressed
from condition_restrictions import cannot_act
from spell_voice_rules import is_silenced


def effective_declaration(state, caster, declaration):
    spell = spells.get_spell(declaration.action)
    if not spell.verbal:
        return declaration
    targets = (
        spells.normalize_target_list(spell, declaration.target_id, declaration.target_ids)
        if declaration.target_ids is not None
        else [declaration.target_id or caster.id]
    )
    redirected = []
    for target_id in targets:
        target = state.get_participant(target_id)
        if (
            target is not None
            and target.choir_reaction is not None
            and not target.is_fallen
            and not target.is_dead
            and not cannot_act(target.conditions)
            and not suppressed(target)
            and not is_silenced(state, target.id)
        ):
            action = target.choir_reaction
            save = check_resolution_save.roll_participant_save(
                caster, action["save"], action["dc"], action["name"], bonus_dice_eligible=False
            )
            if not save.success:
                target_id = caster.id
        redirected.append(target_id)
    if declaration.target_ids is not None:
        normalized = spells.normalize_target_list(spell, None, list(dict.fromkeys(redirected)))
        return replace(declaration, target_id=None, target_ids=normalized)
    return replace(declaration, target_id=redirected[0])
