"""Rules for the warrior's core combat actions."""

import abilities
import ability_persistence
import check_resolution_save
import combat_melee_approach
import combat_recharge
import combat_spell_heal
import dice
from combat_ability_gate import (
    CUNNING_ACTION,
    CUNNING_RIDERS,
    DEVASTATING_STRIKE,
    RALLYING_SHOUT,
    SECOND_WIND,
    SHIELD_BASH,
    SHIELD_BASH_RIDER,
    DeclaredAbility,
    require_rally_target,
)
from combat_ability_save import player_ability_dc
from combat_condition_landing import _land_condition_on_one
from combat_down import damage_target_unavailable
from combat_fate_rolls import PacketRolls, packet_save
from combat_legendary_resistance import finalize_save, override_fields
from combat_participant import CombatParticipant
from declarations import Declaration, DeclarationType
from session_data import CombatState


def require_targets(
    state: CombatState, actor: CombatParticipant, decl: Declaration, ability: abilities.Ability
) -> None:
    if ability.id == SECOND_WIND:
        if decl.target_ids or decl.target_id not in (None, actor.id):
            raise ValueError("Second Wind only heals the warrior using it.")
        if not abilities.owns_ability(actor.archetype_id, actor.level, ability, owns_elective=False):
            raise ValueError(f"{actor.name} hasn't learned Second Wind.")
        if not combat_recharge.available(actor, combat_recharge.SECOND_WIND_BUDGET):
            raise ValueError("Second Wind has already been used in this combat.")
    if ability.id == DEVASTATING_STRIKE:
        target = state.get_participant(decl.target_id) if decl.target_id else None
        if decl.target_ids or target is None or target.is_ally or damage_target_unavailable(target):
            raise ValueError("Devastating Strike requires one standing foe.")
    if ability.id == RALLYING_SHOUT:
        standing = {p.id for p in state.participants if p.is_ally and p.hp_current > 0 and not p.is_fallen}
        require_rally_target(actor.id, decl.target_id if not decl.target_ids else None, standing)


async def second_wind(
    state: CombatState, actor: CombatParticipant, resolved: DeclaredAbility, *, conn, queries, mutations
) -> dict:
    await pay(actor.id, resolved, queries=queries, conn=conn)
    combat_recharge.spend(actor, combat_recharge.SECOND_WIND_BUDGET, state.round_number)
    rolled = dice.roll("1d10").total
    healed = await combat_spell_heal.restore(actor, rolled + actor.level, conn=conn, mutations=mutations)
    return {
        "actor_id": actor.id,
        "resolved": True,
        "declaration_type": "ability",
        "action": SECOND_WIND,
        "rolled": rolled,
        "healed": healed,
        "hp_current": actor.hp_current,
    }


def attack_ability(decl: Declaration) -> str | None:
    if decl.type is DeclarationType.ATTACK and decl.rider in CUNNING_RIDERS:
        return CUNNING_ACTION
    if decl.type is DeclarationType.ATTACK and decl.rider == SHIELD_BASH_RIDER:
        return SHIELD_BASH
    if decl.type is DeclarationType.ABILITY and decl.action == DEVASTATING_STRIKE:
        return DEVASTATING_STRIKE
    return None


def main_hand(player: dict) -> dict:
    weapon = player.get("equipment", {}).get("main_hand")
    if not isinstance(weapon, dict) or not combat_melee_approach.is_melee(weapon):
        raise ValueError("Devastating Strike requires an equipped main-hand melee weapon.")
    return weapon


async def pay(player_id: str, resolved: DeclaredAbility, *, queries, conn) -> None:
    from combat_ability import _deduct_ability_cost

    ability, variant = resolved
    await _deduct_ability_cost(player_id, ability, variant, persistence=ability_persistence, queries=queries, conn=conn)


async def bash_save(
    session,
    state: CombatState,
    actor: CombatParticipant,
    target: CombatParticipant,
    receipt: dict,
    *,
    progress: PacketRolls | None,
) -> None:
    if not receipt["hit"] or damage_target_unavailable(target):
        return
    save = await packet_save(
        progress,
        session,
        target.id,
        "stunned",
        lambda: check_resolution_save.roll_participant_save(
            target,
            "constitution",
            player_ability_dc(actor, "strength"),
            "stunned",
            originating_participant_id=actor.id,
            combat_state=state,
        ),
    )
    if save is None:
        return
    save = finalize_save(state, target, save, failed_conditions=("stunned",))
    receipt.update(override_fields(save), save_success=save.success)
    if save.success:
        receipt["condition_resisted"] = "stunned"
    elif _land_condition_on_one(state, target.id, actor, "stunned", SHIELD_BASH, packet=receipt, duration=1):
        receipt["condition_inflicted"] = "stunned"
    else:
        receipt["condition_immune"] = "stunned"
