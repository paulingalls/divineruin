"""Martial combat abilities and their resolution receipts."""

import abilities
import ability_persistence
import check_resolution_save
import combat_melee_approach
import combat_recharge
import combat_spell_heal
import dice
from combat_ability_gate import (
    COORDINATED_ASSAULT,
    CUNNING_ACTION,
    CUNNING_RIDERS,
    DEVASTATING_STRIKE,
    DIRECT_STRIKE,
    MARSHAL_ORDERS,
    RALLYING_SHOUT,
    SECOND_WIND,
    SHIELD_BASH,
    SHIELD_BASH_RIDER,
    DeclaredAbility,
    declared_ability,
    require_rally_target,
)
from combat_ability_save import player_ability_dc
from combat_condition_landing import _land_condition_on_one
from combat_down import damage_target_unavailable
from combat_fate_rolls import PacketRolls, packet_save
from combat_legendary_resistance import finalize_save, override_fields
from combat_participant import CombatParticipant
from condition_sources import DeliveryRefused
from declarations import Declaration, DeclarationType
from patron_synergy_combat import grant_marshal_rally
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


def _order_targets(decl: Declaration) -> list[str]:
    return decl.target_ids or ([decl.target_id] if decl.target_id is not None else [])


def order_recipients(
    state: CombatState, actor: CombatParticipant, decl: Declaration, ability: abilities.Ability
) -> tuple[list[str], list[str]]:
    targets = _order_targets(decl)
    if ability.id == DIRECT_STRIKE:
        if len(targets) != 2:
            raise DeliveryRefused(f"{ability.name} requires one ally and one foe.")
        allies, foes = targets[:1], targets[1:]
    elif ability.id == COORDINATED_ASSAULT:
        if len(targets) != 2 or len(set(targets)) != len(targets):
            raise DeliveryRefused(f"{ability.name} requires two distinct allies.")
        allies, foes = targets, []
    else:
        if len(targets) != 1:
            raise DeliveryRefused(f"{ability.name} requires one ally.")
        allies, foes = targets, []

    for index, target_id in enumerate(targets):
        target = state.get_participant(target_id)
        if target is None:
            raise DeliveryRefused(f"{ability.name}: Unknown order target {target_id!r}.")
        if index < len(allies):
            if not target.is_ally:
                raise DeliveryRefused(f"{ability.name} requires an ally in the command slot.")
            if target_id == actor.id:
                raise DeliveryRefused(f"{actor.name} cannot command themselves with {ability.name}.")
            if target.hp_current <= 0 or target.is_fallen:
                raise DeliveryRefused(f"{ability.name} requires a standing ally. {target.name} is unavailable.")
        else:
            if target.is_ally or target.is_structure:
                raise DeliveryRefused(f"{ability.name} requires a foe in the second slot.")
            if damage_target_unavailable(target):
                raise DeliveryRefused(f"{ability.name} requires a standing foe. {target.name} is unavailable.")
    return allies, foes


async def preflight_orders(state: CombatState, *, queries) -> None:
    from combat_ability import _gate_ability_condition

    for actor in state.participants:
        raw = state.pending_declarations.get(actor.id, {})
        if actor.type != "player" or raw.get("type") != DeclarationType.ABILITY:
            continue
        resolved = declared_ability(raw.get("action"))
        if resolved is None or resolved[0].id not in MARSHAL_ORDERS:
            continue
        ability, variant = resolved
        player = await queries.get_player(actor.id)
        if player is None:
            raise ValueError(f"Unknown player: {actor.id}")
        owned_elective = ability.ability_type == "elective" and await ability_persistence.owns_elective(
            actor.id, ability.id
        )
        if not abilities.owns_ability(player.get("class"), player["level"], ability, owns_elective=owned_elective):
            raise ValueError(f"{actor.name} hasn't learned {ability.name}.")
        _gate_ability_condition(player, ability, variant)


async def narrated_order(
    state: CombatState, actor: CombatParticipant, decl: Declaration, resolved: DeclaredAbility, *, conn, queries
) -> dict:
    ability, variant = resolved
    authored = variant or ability
    allies, _ = order_recipients(state, actor, decl, ability)
    await pay(actor.id, resolved, queries=queries, conn=conn)
    grant = await grant_marshal_rally(state, actor.id, allies[0], queries=queries, conn=conn)
    return {
        **({"rally_grant": grant} if grant is not None else {}),
        "actor_id": actor.id,
        "resolved": True,
        "declaration_type": "ability",
        "action": decl.action,
        "name": ability.name,
        "target_ids": _order_targets(decl),
        "effect_resolution": "narrated",
        "effect": authored.effect,
        "narration_cue": authored.narration_cue,
        "deducted": {"focus": authored.cost.focus, "stamina": authored.cost.stamina},
    }


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
