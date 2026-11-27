"""Hostile spell saves and condition delivery on the working phase state."""

from dataclasses import replace
from functools import partial

import check_resolution_save
import concentration_break
import conditions
import encounter_facts
from combat_condition_landing import land_condition_on_participant
from combat_fate_rolls import PacketRolls, packet_save
from combat_legendary_resistance import finalize_save, override_fields
from combat_participant import CombatParticipant
from combat_spell_save import spell_save_dc
from combat_state import CombatState
from condition_produce import resolve_effective_targets
from declarations import Declaration
from session_data import SessionData
from spells import Spell


def validate_target(
    state: CombatState, caster: CombatParticipant, declaration: Declaration, spell: Spell
) -> CombatParticipant:
    targets = resolve_effective_targets(declaration.target_ids, declaration.target_id, self_value=caster.id)
    if len(targets) != 1:
        raise ValueError(f"{spell.name} requires one standing enemy")
    target = state.get_participant(targets[0])
    if target is None or target.is_ally == caster.is_ally or target.is_fallen:
        raise ValueError(f"{spell.name} requires one standing enemy")
    assert spell.save_condition is not None
    category = "hollow" if target.hollow is not None else target.category
    required = spell.save_condition.get("target_category", category)
    if category != required:
        raise ValueError(f"{spell.name} requires a {required} target")
    return target


def _refuse(packet: dict, outcome: str, cue: str) -> None:
    packet["condition_outcome"] = outcome
    packet["effect"] = packet["narration_cue"] = cue


async def land(
    session: SessionData,
    state: CombatState,
    caster: CombatParticipant,
    declaration: Declaration,
    spell: Spell,
    packet: dict,
    *,
    progress: PacketRolls | None,
    conn,
) -> None:
    profile = spell.save_condition
    assert profile is not None
    try:
        target = validate_target(state, caster, declaration, spell)
    except ValueError as exc:
        _refuse(packet, "ineligible_target", str(exc))
        return
    packet["target_id"] = target.id
    if spell.concentration and any(held.get("source") == spell.id for held in target.conditions):
        # The cast already ended this caster's prior concentration and its holds, so a remaining
        # hold from this spell belongs to another caster. A refresh would move it to this caster,
        # so this cast settles with no effect and does not leave this caster concentrating on it.
        await concentration_break.end_concentration(session, caster.id, combat_state=state, conn=conn)
        _refuse(
            packet,
            "already_held",
            f"{target.name} is already held by another caster. This casting takes no hold, and its concentration ends.",
        )
        return
    if target.hp_current > profile.get("hp_ceiling", target.hp_current):
        _refuse(
            packet,
            "failed_unknown_to_caster",
            "The spell failed silently. The caster does not know. Describe only the casting.",
        )
        return
    condition = profile["condition"]
    if (ability := profile["save"]) is not None:
        attribute = profile.get("attribute")
        assert attribute is not None
        dc = spell_save_dc(caster, attribute, packet)
        save = await packet_save(
            progress,
            session,
            target.id,
            spell.name,
            partial(
                check_resolution_save.roll_participant_save,
                target,
                ability,
                dc,
                spell.name,
                originating_participant_id=caster.id,
                combat_state=state,
            ),
            state=state,
            conn=conn,
        )
        if save is None:
            return
        target.conditions = conditions.remove_conditions(target.conditions, save.consumed_conditions)
        save = finalize_save(state, target, save, failed_conditions=(condition,))
        packet["save"] = {
            "attribute": save.save_type,
            "roll": save.roll,
            "total": save.total,
            "dc": save.dc,
            "success": save.success,
            **override_fields(save),
            **save.oath_fields(),
            **encounter_facts.rally_receipt(target.id, save.rally_sources),
        }
        if save.success:
            _refuse(packet, "resisted", save.narrative_hint if save.success_override else f"{target.name} resisted.")
            return
    if land_condition_on_participant(
        state,
        caster,
        replace(declaration, target_id=target.id),
        condition,
        spell.id,
        packet=packet,
        tick_save=profile["resave"][:3],
    ):
        packet["condition_inflicted"] = condition
        packet["condition_targets"] = [target.id]
    else:
        packet["condition_immune"] = condition
        _refuse(packet, "condition_immune", f"{target.name} is immune to {condition}.")


def land_damage_rider(
    state: CombatState,
    caster: CombatParticipant,
    declaration: Declaration,
    target: CombatParticipant,
    spell_id: str,
    rider: dict,
    receipt: dict,
) -> None:
    save = receipt.get("save")
    landed = not save["success"] if save is not None else receipt.get("hit") is True
    if not landed or target.is_fallen or target.is_structure:
        return

    condition = rider["condition"]
    receipt["condition_source"] = spell_id
    if condition == "stunned" and conditions.has_condition(target.conditions, condition):
        receipt["condition_already_held"] = condition
        return

    expires = rider["expires"]
    on_caster_start = expires == "caster_turn_start"
    turns = (state.ally_continuation or {}).get("turns", [])
    # An ally whose turn has started or passed gets the next turn in the following round.
    skip_first_wrap = target.is_ally and not any(actor_id == target.id for actor_id, _ in turns[1:])
    if land_condition_on_participant(
        state,
        caster,
        declaration,
        condition,
        spell_id,
        packet=receipt,
        duration=None if on_caster_start else 1,
        skip_first_wrap=skip_first_wrap,
        originating_participant_id=caster.id if on_caster_start else None,
    ):
        receipt.update(condition_inflicted=condition, condition_expires=expires)
    else:
        receipt["condition_immune"] = condition
