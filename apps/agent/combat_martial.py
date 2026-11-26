"""Martial combat abilities, weapon riders and order receipts."""

from livekit.agents.llm import ToolError

import abilities
import ability_persistence
import check_resolution
import check_resolution_save
import combat_melee_approach
import combat_order_riders
import combat_recharge
import combat_spatial
import combat_spell_heal
import concealment
import conditions
import dice
import mentor_variants
from combat_ability_gate import (
    BLADE_FLURRY,
    CLEAVING_BLOW,
    COORDINATED_ASSAULT,
    CRIPPLING_STRIKE,
    CRIPPLING_STRIKE_RIDER,
    CUNNING_ACTION,
    CUNNING_RIDERS,
    DEVASTATING_STRIKE,
    DIRECT_STRIKE,
    ELECTIVE_ATTACK_RIDERS,
    ELECTIVE_RIDER_ABILITIES,
    EXPLOIT_WEAKNESS,
    IRON_STANCE_ABILITY,
    MARSHAL_ORDERS,
    MULTI_TARGET_WEAPON_ABILITIES,
    QUICK_FINGERS,
    QUICK_FINGERS_RIDER,
    RALLYING_SHOUT,
    SECOND_WIND,
    SHADOW_STEP,
    SHIELD_BASH,
    SHIELD_BASH_RIDER,
    SINGLE_TARGET_WEAPON_ABILITIES,
    SMOKE_BOMB,
    VANISH,
    WHIRLWIND,
    DeclaredAbility,
    declared_ability,
    require_rally_target,
)
from combat_ability_save import player_ability_dc
from combat_condition_landing import _land_condition_on_one
from combat_down import damage_target_unavailable
from combat_fate_rolls import PacketRolls, packet_save
from combat_legendary_resistance import finalize_save, override_fields
from combat_order_riders import FIELD_MEDIC
from combat_participant import CombatParticipant
from combat_structures import blocked_reason, line_blocker
from condition_catalog import CRIPPLED, STUDIED_WEAKNESS
from condition_sources import DeliveryRefused, require_hostile_targets
from declarations import Declaration, DeclarationType
from mentor_variants import MentorVariant
from patron_synergy_combat import grant_marshal_rally
from session_data import CombatState


def require_targets(
    state: CombatState, actor: CombatParticipant, decl: Declaration, ability: abilities.Ability
) -> None:
    if ability.id in (VANISH, SMOKE_BOMB, SHADOW_STEP) and (decl.target_ids or decl.target_id not in (None, actor.id)):
        raise ValueError(f"{ability.name} targets only the rogue.")
    if ability.id == IRON_STANCE_ABILITY and (decl.target_ids or decl.target_id not in (None, actor.id)):
        raise ValueError("Iron Stance only protects the warrior using it.")
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
    if ability.id == BLADE_FLURRY:
        target = state.get_participant(decl.target_id) if decl.target_id else None
        if decl.target_ids or not standing_foe(target):
            raise ValueError("Blade Flurry requires one standing foe.")
    if ability.id == CLEAVING_BLOW:
        targets = cleave_targets(decl)
        if (
            (decl.target_id is not None and decl.target_ids)
            or not 1 <= len(targets) <= 2
            or len(set(targets)) != len(targets)
            or any(not standing_foe(state.get_participant(tid)) for tid in targets)
        ):
            raise ValueError("Cleaving Blow requires one or two distinct standing foes.")
    if ability.id == WHIRLWIND and (decl.target_id is not None or decl.target_ids):
        raise ValueError("Whirlwind chooses its own targets. Leave targets empty.")
    if ability.id == EXPLOIT_WEAKNESS and _study_target(state, decl) is None:
        raise ValueError("Exploit Weakness requires one standing foe.")
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
            if ability.id == FIELD_MEDIC and target.type != "player":
                raise DeliveryRefused(f"{ability.name} requires a player ally.")
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


async def resolve_order(
    state: CombatState, actor: CombatParticipant, decl: Declaration, resolved: DeclaredAbility, *, conn, queries
) -> dict:
    ability = resolved[0]
    allies, foes = order_recipients(state, actor, decl, ability)
    await pay(actor.id, resolved, queries=queries, conn=conn)
    grant = await grant_marshal_rally(state, actor.id, allies[0], queries=queries, conn=conn)
    if ability.id == DIRECT_STRIKE:
        rider = combat_order_riders.grant_direct_strike(state, actor.id, allies[0], foes[0])
    elif ability.id == COORDINATED_ASSAULT:
        rider = combat_order_riders.grant_coordinated_assault(state, actor.id, allies)
    elif ability.id == FIELD_MEDIC:
        rider = combat_order_riders.grant_field_medic(state, actor.id, allies[0])
    else:
        raise ValueError(f"No order rider for {ability.id}")
    return {**order_receipt(actor, decl, resolved, grant, effect_resolution="engine"), "order_rider_grant": rider}


def order_receipt(
    actor: CombatParticipant,
    decl: Declaration,
    resolved: DeclaredAbility,
    grant: dict | None,
    *,
    effect_resolution: str,
) -> dict:
    ability, variant = resolved
    authored = variant or ability
    return {
        **({"rally_grant": grant} if grant is not None else {}),
        "actor_id": actor.id,
        "resolved": True,
        "declaration_type": "ability",
        "action": decl.action,
        "name": ability.name,
        "target_ids": _order_targets(decl),
        "effect_resolution": effect_resolution,
        "effect": authored.effect,
        "narration_cue": authored.narration_cue,
        "deducted": {"focus": authored.cost.focus, "stamina": authored.cost.stamina},
    }


def cleave_targets(decl: Declaration) -> list[str]:
    return [decl.target_id] if decl.target_id is not None else list(decl.target_ids or ())


def standing_foe(target: CombatParticipant | None) -> bool:
    return (
        target is not None
        and not target.is_ally
        and not target.is_structure
        and not target.is_fallen
        and not target.is_dead
        and target.hp_current > 0
    )


def reach_refusal(state: CombatState, actor: CombatParticipant, target_id: str, weapon: dict) -> str | None:
    spatial = combat_spatial.require_spatial(state)
    origin = combat_spatial.position(spatial, actor.id)
    destination = combat_spatial.position(spatial, target_id)
    if combat_spatial.distance(origin, destination) > combat_melee_approach.melee_reach(weapon):
        return f"{target_id} is outside main-hand melee reach."
    if wall := line_blocker(state, actor.id, target_id, melee=True):
        return blocked_reason(wall)
    return None


def whirlwind_targets(state: CombatState, actor: CombatParticipant, weapon: dict) -> list[str]:
    targets = sorted(
        p.id for p in state.participants if standing_foe(p) and reach_refusal(state, actor, p.id, weapon) is None
    )
    require_hostile_targets(state, actor, targets)
    return targets


def cleave_faces() -> list[int]:
    return [check_resolution.dice_roll("d20").total for _ in range(2)]


def skip_swing(target_id: str, reason: str) -> dict:
    return {"target_id": target_id, "skipped": True, "reason": reason}


def _study_target(state: CombatState, decl: Declaration) -> CombatParticipant | None:
    target = state.get_participant(decl.target_id) if decl.target_id else None
    if (
        target is None
        or target.is_ally
        or target.is_structure
        or target.hp_current <= 0
        or damage_target_unavailable(target)
    ):
        return None
    return target


async def exploit_weakness(
    state: CombatState, actor: CombatParticipant, decl: Declaration, resolved: DeclaredAbility, *, queries, conn
) -> dict:
    from combat_ability import _with_variant

    target = _study_target(state, decl)
    summary = {"actor_id": actor.id, "declaration_type": "ability", "action": EXPLOIT_WEAKNESS, "resolved": False}
    if target is None:
        return {**summary, "reason": "Exploit Weakness requires one standing foe."}
    variant = await pay(actor.id, resolved, queries=queries, conn=conn)
    actor.conditions = conditions.apply_condition(actor.conditions, STUDIED_WEAKNESS, source=target.id, duration=2)
    return _with_variant({**summary, "resolved": True, "target_id": target.id}, variant)


def cripple(state: CombatState, actor: CombatParticipant, target: CombatParticipant, receipt: dict) -> None:
    if not receipt["hit"] or damage_target_unavailable(target):
        return
    if _land_condition_on_one(state, target.id, actor, CRIPPLED, CRIPPLING_STRIKE, packet=receipt, duration=1):
        receipt["condition_inflicted"] = CRIPPLED
    else:
        receipt["condition_immune"] = CRIPPLED


async def vanish(actor: CombatParticipant, resolved: DeclaredAbility, *, conn, queries) -> dict:
    from combat_ability import _with_variant

    ability, _ = resolved
    variant = await pay(actor.id, resolved, queries=queries, conn=conn)
    cost = (variant or ability).cost
    player = await queries.get_player(actor.id, conn=conn, for_update=True)
    if player is None:
        raise ToolError(f"Unknown player: {actor.id}")
    return _with_variant(
        {
            "actor_id": actor.id,
            "resolved": True,
            "declaration_type": "ability",
            "action": VANISH,
            "deducted": {"focus": cost.focus, "stamina": cost.stamina},
            "concealment": await concealment.transition(actor.id, player, True, combat_only=True, conn=conn),
        },
        variant,
    )


async def smoke_bomb(state: CombatState, actor: CombatParticipant, resolved: DeclaredAbility, *, conn, queries) -> dict:
    from combat_ability import _with_variant

    ability, _ = resolved
    variant = await pay(actor.id, resolved, queries=queries, conn=conn)
    cost = (variant or ability).cost
    return _with_variant(
        {
            "actor_id": actor.id,
            "resolved": True,
            "declaration_type": "ability",
            "action": SMOKE_BOMB,
            "deducted": {"focus": cost.focus, "stamina": cost.stamina},
            "zone_id": combat_spatial.add_smoke(state, actor.id),
        },
        variant,
    )


async def second_wind(
    state: CombatState, actor: CombatParticipant, resolved: DeclaredAbility, *, conn, queries, mutations
) -> dict:
    await pay(actor.id, resolved, queries=queries, conn=conn)
    combat_recharge.spend(actor, combat_recharge.SECOND_WIND_BUDGET, state.round_number)
    rolled = dice.roll("1d10").total
    healed = await combat_spell_heal.restore(
        actor, rolled + actor.level, conn=conn, mutations=mutations, queries=queries
    )
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
    if decl.type is DeclarationType.RETREAT and decl.rider == "disengage":
        return CUNNING_ACTION
    if decl.type is DeclarationType.ATTACK and decl.rider == SHIELD_BASH_RIDER:
        return SHIELD_BASH
    if decl.type is DeclarationType.ATTACK and decl.rider == CRIPPLING_STRIKE_RIDER:
        return CRIPPLING_STRIKE
    if decl.type is DeclarationType.ATTACK and decl.rider == QUICK_FINGERS_RIDER:
        return QUICK_FINGERS
    if (
        decl.type is DeclarationType.ABILITY
        and (resolved := declared_ability(decl.action)) is not None
        and resolved[0].id in (*SINGLE_TARGET_WEAPON_ABILITIES, *MULTI_TARGET_WEAPON_ABILITIES)
    ):
        return resolved[0].id
    if decl.type is DeclarationType.ATTACK and decl.rider is not None:
        return ELECTIVE_ATTACK_RIDERS.get(decl.rider)
    return None


def main_hand(player: dict, ability_name: str) -> dict:
    weapon = player.get("equipment", {}).get("main_hand")
    if not isinstance(weapon, dict) or not combat_melee_approach.is_melee(weapon):
        raise ValueError(f"{ability_name} requires an equipped main-hand melee weapon.")
    return weapon


async def active_rider_variant(player_id: str, ability_id: str, *, conn) -> MentorVariant | None:
    variant_id = await ability_persistence.get_active_variant(player_id, ability_id, conn=conn)
    return mentor_variants.get_variant(ability_id, variant_id) if variant_id is not None else None


async def pay(player_id: str, resolved: DeclaredAbility, *, queries, conn) -> MentorVariant | None:
    from combat_ability import _deduct_ability_cost

    ability, variant = resolved
    if ability.id in ELECTIVE_RIDER_ABILITIES:
        variant = await active_rider_variant(player_id, ability.id, conn=conn)
    await _deduct_ability_cost(player_id, ability, variant, persistence=ability_persistence, queries=queries, conn=conn)
    return variant


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
