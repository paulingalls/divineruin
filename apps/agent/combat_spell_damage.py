"""Land catalog spell damage beside other cast effects in the caller's phase transaction."""

from dataclasses import asdict, replace
from functools import partial

import check_resolution_attack
import check_resolution_save
import combat_damage_affinity
import concentration_break
import conditions
import db_mutations
import db_queries
import dice
import spells
import thyra_seasons
from combat_attack_roll import attack_roll_inputs
from combat_damage_results import AutomaticDamageResult, SaveDamageResult
from combat_fate_rolls import packet_save
from combat_legendary_resistance import finalize_save, override_fields
from combat_spell_profile import DICE, scaled
from combat_support import _resolve_attack_packet, apply_attack_result, apply_rolled_attack
from patron_synergy_combat import attack_player
from rules_engine import attribute_modifier, proficiency_bonus
from zhael_fate import candidates


def _components(profile, caster, target, cast_packet, choice):
    result = []
    for i, component in enumerate(profile["components"]):
        match = DICE.fullmatch(component["dice"])
        assert match is not None
        count, sides, flat = (int(n or 0) for n in match.groups())
        if i == 0:
            count = scaled(profile, "scaling", count, caster.level)
            if target.hollow and "hollow_dice" in profile:
                count = profile["hollow_dice"]
            count += cast_packet["resonance_modifiers"]["damage_dice"]
        assert count >= 0
        notation = f"{count}d{sides}" if count else "0"
        if flat and count:
            notation += f"+{flat}"
        damage_type = choice if component["damage_type"] == "choice" else component["damage_type"]
        result.append({"dice": notation, "damage_type": cast_packet.get("damage_type_override", damage_type)})
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


async def _land_one(
    session,
    state,
    caster,
    declaration,
    cast_packet,
    *,
    conn,
    delivery=None,
    sink=None,
    mutations=db_mutations,
    queries=db_queries,
    resolver=check_resolution_attack,
    concentration_break_mod=concentration_break,
    progress=None,
):
    spell = spells.get_spell(declaration.action)
    profile = spell.combat_damage
    if profile is None:
        return
    if profile["resolution"] == "deferred":
        cast_packet["deferred"] = [{"effect": "damage", "not_affected": True, "reason": profile["deferred"]}]
        return
    if not declaration.target_id and profile.get("optional_target"):
        return
    target = state.get_participant(declaration.target_id)
    # A held attack resumes against the same recipient even if its damage receipt already dropped it.
    resuming = progress is not None and ("prepared" in progress.steps or "damage_receipt" in progress.steps)
    if target is None or (target.is_fallen and not resuming):
        cast_packet["damage_result"] = {
            "damage": 0,
            "resolved": False,
            "reason": "Declared recipient is no longer available; no damage landed.",
        }
        return
    profile = dict(profile)
    if delivery and delivery.get("secondary"):
        profile["components"] = [{**c, "dice": profile["recipients"]["secondary_dice"]} for c in profile["components"]]
    components = _components(profile, caster, target, cast_packet, declaration.argument_type)
    if "damage_dice" in cast_packet:
        cast_packet["damage_dice"] = components[0]["dice"]
    action = {
        "magical": True,
        "name": spell.name,
        "spell_id": spell.id,
        "spell_source": spell.source,
        "damage": components[0]["dice"],
        "damage_type": components[0]["damage_type"],
        "ranged": profile.get("ranged", False),
        "governing_attribute": profile.get("attribute"),
        "damage_attribute": profile.get("damage_attribute", False),
    }
    if profile["resolution"] == "attack":
        result = await _land_attack(
            session,
            state,
            caster,
            target,
            action,
            conn=conn,
            sink=sink,
            mutations=mutations,
            queries=queries,
            resolver=resolver,
            concentration_break_mod=concentration_break_mod,
            progress=progress,
        )
        if result is None:
            return
        caster.conditions = conditions.remove_conditions(caster.conditions, result.get("consumed_conditions", ()))
    else:
        if progress is not None and "damage_receipt" in progress.steps:
            # A resumed receipt (a held concentration or Fortitude save) already rolled this blow.
            roll, save_info = None, progress.steps.get("save_info")
        else:
            rolled = await _roll_save_damage(
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
                conn=conn,
                queries=queries,
            )
            if rolled is None:
                return
            roll, save_info = rolled
            if progress is not None:
                progress.steps["save_info"] = save_info
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
            progress=progress,
        )
        if progress is not None:
            if progress.paused:
                return
            progress.steps.pop("save_info", None)
        if save_info is not None:
            result["save"] = save_info
    result["target_id"] = target.id
    result["target_hp_current"] = target.hp_current
    if delivery and "dart_indices" in delivery:
        result["darts"] = [{"index": i, "damage": delivery["dart_rolls"][i]} for i in delivery["dart_indices"]]
        result["dart_indices"] = delivery["dart_indices"]
    cast_packet["damage_result"] = result
    deferred = _deferred(state, caster, target, profile)
    if deferred:
        cast_packet["deferred"] = deferred


async def _roll_save_damage(
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
        dc = (
            8
            + proficiency_bonus(caster.level)
            + attribute_modifier(caster.attributes.get(profile["attribute"], 10))
            + cast_packet["resonance_modifiers"]["dc"]
        )
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
        save = finalize_save(state, target, save, failed_damage=adjusted.damage)
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
    }
    return roll, save_info


async def _land_attack(
    session,
    state,
    caster,
    target,
    action,
    *,
    conn,
    sink,
    mutations,
    queries,
    resolver,
    concentration_break_mod,
    progress,
):
    """Resolve a spell attack; with ``progress``, a Zhael-eligible d20 is held before damage.

    Returns None while a held roll (or a deferred concentration save) is pending."""
    ac_bonus = state.ac_modifiers.get(target.id, 0)
    prepared = None
    if progress is not None and "prepared" in progress.steps:
        prepared = check_resolution_attack.PreparedAttack.from_dict(progress.steps.pop("prepared"))
        attacker_data = progress.steps.pop("attacker_data")
    elif progress is not None and "damage_receipt" not in progress.steps:
        eligible = await candidates(session, queries=queries, conn=conn)
        if eligible.choices(caster.id):
            player = await attack_player(caster, queries=queries, conn=conn)
            defender = await attack_player(target, queries=queries, conn=conn)
            attacker_data, ac, modifier = attack_roll_inputs(
                caster,
                target,
                ac_bonus,
                state,
                action,
                weapon_attack=False,
                player=player,
                defender=defender,
                season=await thyra_seasons.season_for(player, conn=conn),
            )
            prepared = check_resolution_attack.prepare_attack(
                attacker_data, action, ac, attack_mod=modifier, target_conditions=target.conditions
            )
            if await progress.phase.hold(
                session,
                "attack",
                caster.id,
                prepared.original,
                prepared.d20,
                queries=queries,
                conn=conn,
                candidates=eligible,
            ):
                frozen = asdict(prepared)
                frozen["consumed"] = list(prepared.consumed)
                progress.steps.update(prepared=frozen, attacker_data=attacker_data)
                return None
    deps = {
        "combat_state": state,
        "conn": conn,
        "sink": sink,
        "mutations": mutations,
        "queries": queries,
        "concentration_break_mod": concentration_break_mod,
        "progress": progress,
    }
    if prepared is None:
        result = await _resolve_attack_packet(
            session,
            caster,
            action,
            target,
            weapon_attack=False,
            target_ac_bonus=ac_bonus,
            resolver=resolver,
            **deps,
        )
    else:
        assert progress is not None
        rolled = check_resolution_attack.finish_attack(
            attacker_data,
            action,
            prepared.d20.dc,
            target.hp_current,
            prepared,
            progress.phase.select(prepared.original),
            damage_mult=caster.damage_mult,
            target_conditions=target.conditions,
        )
        result = await apply_rolled_attack(session, caster, action, target, rolled, prepared.d20.dc, **deps)
    if progress is not None and progress.paused:
        return None
    return result


async def land(session, state, caster, declaration, cast_packet, *, conn, deliveries=None, progress=None, **deps):
    """Land a cast's catalog damage. With ``progress`` every held d20 (an attack roll, or each
    recipient's save, in delivery order) pauses the landing; recipients already landed are kept in
    ``progress.steps["landed"]`` so a resume never lands one twice."""
    if deliveries is None:
        await _land_one(session, state, caster, declaration, cast_packet, conn=conn, progress=progress, **deps)
        if progress is not None and progress.paused:
            return
        if "damage_result" in cast_packet:
            cast_packet["damage_results"] = [cast_packet["damage_result"]]
        return
    grouped = {}
    for delivery in deliveries:
        target_id = delivery["target_id"]
        if target_id in grouped and "dart_indices" in delivery:
            grouped[target_id]["dart_indices"].extend(delivery["dart_indices"])
        elif target_id not in grouped:
            grouped[target_id] = dict(delivery)
    deliveries = list(grouped.values())
    profile = spells.get_spell(declaration.action).combat_damage
    assert profile is not None
    if deliveries and "dart_indices" in deliveries[0]:
        indices = sorted(index for delivery in deliveries for index in delivery["dart_indices"])
        first_target = state.get_participant(deliveries[0]["target_id"])
        first_dice = _components(profile, caster, first_target, cast_packet, declaration.argument_type)[0]["dice"]
        base = profile["components"][0]["dice"]
        notations = {index: first_dice if index == 0 else base for index in indices}
        rolls = {index: dice.roll(n).total if n != "0" else 0 for index, n in notations.items()}
        deliveries = [{**delivery, "dart_rolls": rolls} for delivery in deliveries]
    landed = progress.steps.setdefault("landed", {}) if progress is not None else {}
    results = []
    for delivery in deliveries:
        target_id = delivery["target_id"]
        if target_id not in landed:
            await _land_one(
                session,
                state,
                caster,
                replace(declaration, target_id=target_id, target_ids=None),
                cast_packet,
                conn=conn,
                delivery=delivery,
                progress=progress.scope(target_id) if progress is not None else None,
                **deps,
            )
            if progress is not None and progress.paused:
                return
            landed[target_id] = cast_packet.pop("damage_result", None)
        result = landed[target_id]
        if result is not None and result.get("resolved") is not False:
            results.append(result)
    cast_packet["damage_results"] = results
    if results:
        cast_packet["damage_result"] = results[0]
    else:
        cast_packet["recipient_status"] = "No effective recipients; no damage landed."
