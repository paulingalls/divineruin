"""Harmonic Shield changes the effective declaration before the single real cast."""

from dataclasses import replace
from functools import partial

import check_resolution_save
import encounter_facts
import spells
from choir_effects import suppressed
from combat_fate_rolls import packet_save
from condition_restrictions import cannot_act
from spell_voice_rules import is_silenced


async def effective_declaration(session, state, caster, declaration, *, progress=None, receipts=None):
    spell = spells.get_spell(declaration.action)
    if not spell.verbal:
        return declaration
    if not declaration.target_id and not declaration.target_ids and (spell.combat_damage or {}).get("optional_target"):
        return declaration
    targets = (
        spells.normalize_target_list(spell, declaration.target_id, declaration.target_ids)
        if declaration.target_ids is not None
        else [declaration.target_id or caster.id]
    )
    redirected = progress.steps.setdefault("targets", []) if progress is not None else []
    for target_id in targets[len(redirected) :]:
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
            save = await packet_save(
                progress,
                session,
                caster.id,
                action["name"],
                partial(
                    check_resolution_save.roll_participant_save,
                    caster,
                    action["save"],
                    action["dc"],
                    action["name"],
                    bonus_dice_eligible=False,
                    combat_state=state,
                ),
                state=state,
            )
            if save is None:
                return None
            if receipts is not None and save.rally_sources:
                receipts.append(
                    {
                        "target_id": target.id,
                        "roll": save.roll,
                        "total": save.total,
                        "dc": save.dc,
                        "success": save.success,
                        **encounter_facts.rally_receipt(caster.id, save.rally_sources),
                    }
                )
            if not save.success:
                target_id = caster.id
        redirected.append(target_id)
    if declaration.target_ids is not None:
        normalized = spells.normalize_target_list(spell, None, list(dict.fromkeys(redirected)))
        return replace(declaration, target_id=None, target_ids=normalized)
    return replace(declaration, target_id=redirected[0])
