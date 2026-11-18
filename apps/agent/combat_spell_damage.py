"""Land catalog spell damage beside other cast effects in the caller's phase transaction."""

import check_resolution_attack
import check_resolution_save
import concentration_break
import conditions
import db_mutations
import db_queries
import dice
import spells
from combat_spell_profile import DICE, scaled
from combat_support import AutomaticDamageResult, SaveDamageResult, _resolve_attack_packet, apply_attack_result
from rules_engine import attribute_modifier, proficiency_bonus


def _components(profile, caster, target, cast, choice):
    result = []
    for i, component in enumerate(profile["components"]):
        match = DICE.fullmatch(component["dice"])
        assert match is not None
        count, sides, flat = (int(n or 0) for n in match.groups())
        if i == 0:
            count = scaled(profile, "scaling", count, caster.level)
            if target.hollow and "hollow_dice" in profile:
                count = profile["hollow_dice"]
            count += cast.packet["resonance_modifiers"]["damage_dice"]
        if count < 0:
            raise ValueError("Spell damage dice became negative")
        notation = f"{count}d{sides}" if count else "0"
        if flat and count:
            notation += f"+{flat}"
        result.append(
            {
                "dice": notation,
                "damage_type": choice if component["damage_type"] == "choice" else component["damage_type"],
            }
        )
    return result


def _deferred(state, caster, target, profile):
    result = []
    if profile.get("deferred"):
        result.append({"effect": "damage", "reason": profile["deferred"], "not_affected": True})
    if profile.get("other_recipients"):
        others = [
            p for p in state.participants if p.is_ally != caster.is_ally and p.id != target.id and not p.is_fallen
        ]
        result.append(
            {
                "effect": "other_recipients",
                "target_ids": [p.id for p in others],
                "targets": [p.name for p in others],
                "not_affected": True,
                "reason": "Only the declared recipient was affected. Other area, arc, or split recipients were NOT affected; do not narrate damage to them. Recipient selection is deferred.",
            }
        )
    return result


async def land(
    session,
    state,
    caster,
    declaration,
    cast,
    *,
    conn,
    sink=None,
    mutations=db_mutations,
    queries=db_queries,
    resolver=check_resolution_attack,
    concentration_break_mod=concentration_break,
):
    spell = spells.get_spell(declaration.action)
    profile = spell.combat_damage
    if profile is None:
        return
    if profile["resolution"] == "deferred":
        cast.packet["deferred"] = [{"effect": "damage", "not_affected": True, "reason": profile["deferred"]}]
        return
    if not declaration.target_id and profile.get("optional_target"):
        return
    target = state.get_participant(declaration.target_id)
    if target is None or target.is_fallen:
        cast.packet["damage_result"] = {
            "damage": 0,
            "resolved": False,
            "reason": "Declared recipient is no longer available; no damage landed.",
        }
        return
    components = _components(profile, caster, target, cast, declaration.argument_type)
    if "damage_dice" in cast.packet:
        cast.packet["damage_dice"] = components[0]["dice"]
    action = {
        "name": spell.name,
        "damage": components[0]["dice"],
        "damage_type": components[0]["damage_type"],
        "ranged": profile.get("ranged", False),
        "governing_attribute": profile.get("attribute"),
        "damage_attribute": profile.get("damage_attribute", False),
    }
    if profile["resolution"] == "attack":
        result = await _resolve_attack_packet(
            session,
            caster,
            action,
            target,
            target_ac_bonus=state.ac_modifiers.get(target.id, 0),
            combat_state=state,
            conn=conn,
            sink=sink,
            mutations=mutations,
            queries=queries,
            resolver=resolver,
            concentration_break_mod=concentration_break_mod,
        )
        caster.conditions = conditions.remove_conditions(caster.conditions, result.get("consumed_conditions", ()))
    else:
        save = None
        dc = None
        plant_blight = spell.id == "primal_blight" and "plant" in target.tags
        if profile["resolution"] == "save" and not plant_blight:
            dc = (
                8
                + proficiency_bonus(caster.level)
                + attribute_modifier(caster.attributes.get(profile["attribute"], 10))
                + cast.packet["resonance_modifiers"]["dc"]
            )
            save = check_resolution_save.roll_participant_save(target, profile["save"], dc, spell.name)
            target.conditions = conditions.remove_conditions(target.conditions, save.consumed_conditions)
        multiplier = scaled(profile, "projectile_scaling", profile.get("projectiles", 1), caster.level)
        rolled = []
        for i, component in enumerate(components):
            total = (
                dice.maximum(component["dice"])
                if plant_blight
                else (dice.roll(component["dice"]).total if component["dice"] != "0" else 0)
            )
            # Resonance changes the first dart only, not every projectile.
            if multiplier > 1:
                base = profile["components"][i]["dice"]
                total += sum(dice.roll(base).total for _ in range(multiplier - 1))
            if i == 0 and component["dice"] != "0" and profile.get("damage_attribute"):
                total += attribute_modifier(caster.attributes.get(profile["attribute"], 10))
            total = max(0, total)
            if save and save.success:
                total = total // 2 if profile["half"] else 0
            if profile.get("restriction") == "undead_hollow" and not (target.hollow or target.category == "undead"):
                total = 0
            rolled.append({**component, "damage": total})
        action["damage_components"] = rolled
        total = sum(c["damage"] for c in rolled)
        roll = AutomaticDamageResult(total, components[0]["damage_type"])
        if save is not None:
            roll = SaveDamageResult(
                save.save_type,
                save.success,
                total,
                components[0]["damage_type"],
                save.narrative_hint,
                save.dramatic,
                save.context,
            )
        result = await apply_attack_result(
            session,
            caster,
            action,
            target,
            roll,
            target.ac,
            combat_state=state,
            conn=conn,
            sink=sink,
            mutations=mutations,
            queries=queries,
            concentration_break_mod=concentration_break_mod,
            publish_roll=False,
        )
        if save is not None:
            result["save"] = {
                "attribute": save.save_type,
                "roll": save.roll,
                "total": save.total,
                "dc": dc,
                "success": save.success,
                "half_on_success": profile["half"],
            }
    result["target_id"] = target.id
    result["target_hp_current"] = target.hp_current
    cast.packet["damage_result"] = result
    deferred = _deferred(state, caster, target, profile)
    if deferred:
        cast.packet["deferred"] = deferred
