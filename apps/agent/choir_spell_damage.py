"""Arcane Bolt's authored formula, consumed by the real Choir cast path."""

from dataclasses import asdict

import check_resolution_attack
import concentration_break
import conditions
import db_mutations
import db_queries
import leveling
from combat_attack_roll import attack_roll_inputs
from combat_support import _resolve_attack_packet, apply_rolled_attack
from zhael_fate import candidates


async def land(
    session,
    state,
    caster,
    declaration,
    cast_packet,
    *,
    conn,
    sink=None,
    mutations=db_mutations,
    queries=db_queries,
    resolver=check_resolution_attack,
    concentration_break_mod=concentration_break,
    progress=None,
):
    if state.choir_encounter is None or declaration.action != "arcane_bolt":
        return
    target = state.get_participant(declaration.target_id)
    if target is None or target.is_fallen:
        raise ValueError("Arcane Bolt requires a live combat target")
    dice_count = (
        int(leveling.cantrip_damage_dice(caster.level).split("d")[0])
        + cast_packet["resonance_modifiers"]["damage_dice"]
    )
    if dice_count < 0:
        raise ValueError("Arcane Bolt damage dice became negative")
    action = {
        "name": "Arcane Bolt",
        "damage": f"{dice_count}d6" if dice_count else "0",
        "damage_type": "force",
        "ranged": True,
        "governing_attribute": "intelligence",
    }
    ac_bonus = state.ac_modifiers.get(target.id, 0)
    prepared = None
    if progress is not None and "prepared" in progress.steps:
        prepared = check_resolution_attack.PreparedAttack.from_dict(progress.steps.pop("prepared"))
        attacker_data = progress.steps.pop("attacker_data")
    elif progress is not None and "damage_receipt" not in progress.steps:
        eligible = await candidates(session, queries=queries, conn=conn)
        if eligible.choices(caster.id):
            attacker_data, ac, modifier = attack_roll_inputs(caster, target, ac_bonus, state)
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
                return
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
        return
    caster.conditions = conditions.remove_conditions(caster.conditions, result.get("consumed_conditions", ()))
    cast_packet["damage_result"] = result
