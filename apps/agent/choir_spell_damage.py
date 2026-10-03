"""Arcane Bolt's authored formula, consumed by the real Choir cast path."""

import check_resolution_attack
import concentration_break
import conditions
import db_mutations
import db_queries
import leveling
from combat_support import _resolve_attack_packet


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
    if state.choir_encounter is None or declaration.action != "arcane_bolt":
        return
    target = state.get_participant(declaration.target_id)
    if target is None or target.is_fallen:
        raise ValueError("Arcane Bolt requires a live combat target")
    dice_count = (
        int(leveling.cantrip_damage_dice(caster.level).split("d")[0])
        + cast.packet["resonance_modifiers"]["damage_dice"]
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
    cast.packet["damage_result"] = result
