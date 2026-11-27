"""Saving throws and damage rolls for catalog spell deliveries."""

from dataclasses import replace
from functools import partial

import check_resolution_save
import combat_damage_affinity
import conditions
import dice
import encounter_facts
import thyra_seasons
from combat_damage_results import AutomaticDamageResult, SaveDamageResult
from combat_fate_rolls import packet_save
from combat_legendary_resistance import finalize_save, override_fields
from combat_spell_profile import scaled
from patron_synergy_combat import attack_player
from rules_engine import attribute_modifier, proficiency_bonus


def spell_save_dc(caster, attribute: str, cast_packet: dict) -> int:
    return (
        8
        + proficiency_bonus(caster.level)
        + attribute_modifier(caster.attributes.get(attribute, 10))
        + cast_packet["resonance_modifiers"]["dc"]
    )


async def roll_save_damage(
    session,
    state,
    profile,
    spell,
    caster,
    target,
    cast_packet,
    components,
    action,
    delivery,
    progress,
    *,
    conn,
    queries,
):
    """Roll the recipient's save, then the damage. Returns ``(roll, save_info)``, or None while a
    Fate's Thread choice holds the save (anyone's d20 is in scope)."""
    dart_indices = delivery.get("dart_indices") if delivery else None
    save = None
    dc = None
    plant_blight = spell.id == "primal_blight" and "plant" in target.tags
    if profile["resolution"] == "save" and not plant_blight:
        dc = spell_save_dc(caster, profile["attribute"], cast_packet)
        save = await packet_save(
            progress,
            session,
            target.id,
            spell.name,
            partial(
                check_resolution_save.roll_participant_save,
                target,
                profile["save"],
                dc,
                spell.name,
                originating_participant_id=caster.id,
                combat_state=state,
            ),
            state=state,
        )
        if save is None:
            return None
        target.conditions = conditions.remove_conditions(target.conditions, save.consumed_conditions)
    multiplier = (
        len(dart_indices)
        if dart_indices is not None
        else scaled(profile, "projectile_scaling", profile.get("projectiles", 1), caster.level)
    )
    player = (
        await attack_player(caster, queries=queries, conn=conn)
        if any(c["damage_type"] in thyra_seasons.DAMAGE_TYPES for c in components)
        else None
    )
    season = await thyra_seasons.season_for(player, conn=conn)
    rolled = []
    for i, component in enumerate(components):
        if dart_indices is not None:
            assert delivery is not None
            total = sum(delivery["dart_rolls"][index] for index in dart_indices)
        else:
            notation = component["dice"]
            total = 0
            if notation != "0":
                total = dice.maximum(notation) if plant_blight else dice.roll(notation).total
                total += thyra_seasons.damage_bonus(player, season, component["damage_type"])
            if multiplier > 1:
                base = profile["components"][i]["dice"]
                total += sum(dice.roll(base).total for _ in range(multiplier - 1))
        if i == 0 and component["dice"] != "0" and profile.get("damage_attribute"):
            total += attribute_modifier(caster.attributes.get(profile["attribute"], 10))
        total = max(0, total)
        # Harmonic Shield can redirect an eligible delivery onto a living caster.
        if profile.get("restriction") == "undead_hollow" and not (target.hollow or target.category == "undead"):
            total = 0
        rolled.append({**component, "damage": total})
    action["damage_components"] = rolled
    total = sum(c["damage"] for c in rolled)
    if save is None:
        return AutomaticDamageResult(total, components[0]["damage_type"]), None
    roll = SaveDamageResult(
        save.save_type,
        save.success,
        total,
        components[0]["damage_type"],
        save.narrative_hint,
        save.dramatic,
        save.context,
    )
    if not save.success:
        _, adjusted = combat_damage_affinity.apply(target, action, roll, state=state)
        rider = profile.get("rider")
        save = finalize_save(
            state,
            target,
            save,
            failed_damage=adjusted.damage,
            failed_conditions=(rider["condition"],) if rider else (),
        )
    if save.success:
        rolled = [{**component, "damage": component["damage"] // 2 if profile["half"] else 0} for component in rolled]
        action["damage_components"] = rolled
        roll = replace(
            roll,
            save_success=True,
            damage=sum(component["damage"] for component in rolled),
            narrative_hint=save.narrative_hint,
        )
    save_info = {
        "attribute": save.save_type,
        "roll": save.roll,
        "total": save.total,
        "dc": dc,
        "success": save.success,
        "half_on_success": profile["half"],
        **override_fields(save),
        **encounter_facts.rally_receipt(target.id, save.rally_sources),
    }
    return roll, save_info
