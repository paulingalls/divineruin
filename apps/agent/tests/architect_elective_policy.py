"""State-based martial elective priorities for the Architect benchmark."""

import abilities
import concealment
from combat_ability_gate import (
    BLADE_FLURRY,
    CLEAVING_BLOW,
    CRIPPLING_STRIKE,
    DIRTY_TRICK,
    EXPLOIT_WEAKNESS,
    IRON_STANCE_ABILITY,
    QUICK_FINGERS,
    QUICK_FINGERS_RIDER,
    SMOKE_BOMB,
    TAUNT,
    VANISH,
    WAR_CRY,
    WHIRLWIND,
    attack_recipe,
    war_cry_targets,
)
from combat_martial import reach_refusal, standing_foe
from combat_melee_approach import finish, plan
from combat_participant import CombatParticipant
from combat_spatial import inside, position, require_spatial, smoke_obscures
from combat_state import CombatState
from combat_structures import line_blocker
from condition_catalog import CRIPPLED, IRON_STANCE, STUDIED_WEAKNESS
from conditions import get_condition_effects, has_condition
from declaration_payloads import AbilityDecl, AttackDecl

UNSTOPPABLE_CHARGE = "warrior_unstoppable_charge"


def affordable(row: dict, loadout: tuple[str, ...], action: str) -> bool:
    return action in loadout and row["stamina"]["current"] >= abilities.get_ability(action).cost.stamina


def ability(actor: CombatParticipant, action: str, *targets: CombatParticipant) -> AbilityDecl:
    return AbilityDecl(
        kind="ability", actor_id=actor.id, action=action, targets=[target.id for target in targets], argument_type=""
    )


def defensive(state: CombatState, actor: CombatParticipant, row: dict, loadout: tuple[str, ...]) -> AbilityDecl | None:
    if actor.hp_current * 2 >= actor.hp_max:
        return None
    if affordable(row, loadout, IRON_STANCE_ABILITY) and not has_condition(actor.conditions, IRON_STANCE):
        return ability(actor, IRON_STANCE_ABILITY)
    if affordable(row, loadout, VANISH) and not concealment.is_concealed(row):
        return ability(actor, VANISH)
    if affordable(row, loadout, SMOKE_BOMB) and not smoke_obscures(require_spatial(state), actor.id, actor.id):
        return ability(actor, SMOKE_BOMB)
    return None


def weapon_attack(actor: CombatParticipant, weapon: dict, target: CombatParticipant, rider: str = "") -> AttackDecl:
    return AttackDecl(
        kind="attack",
        actor_id=actor.id,
        action=weapon["name"],
        target_id=target.id,
        held_item_id="",
        rider=rider,
        quick_fingers_mode="steal" if rider == QUICK_FINGERS_RIDER else "",
        quick_fingers_item="",
        reshape=[],
    )


def can_strike(state: CombatState, actor: CombatParticipant, target: CombatParticipant, weapon: dict) -> bool:
    facts, route = plan(state, actor, target, weapon, {})
    if route is not None:
        facts = finish({**facts, "destination": route["endpoint"]}, route["target"], route["reach"])
    return facts["attack_resolved"]


def sneak_attack_opening(state: CombatState, actor: CombatParticipant, target: CombatParticipant, row: dict) -> bool:
    spatial = require_spatial(state)
    if smoke_obscures(spatial, actor.id, target.id):
        return False
    return (
        concealment.is_concealed(row)
        or "attack" in get_condition_effects(actor.conditions).advantage_scopes
        or any(
            ally.is_ally
            and ally.id != actor.id
            and not ally.is_fallen
            and inside(position(spatial, ally.id), position(spatial, target.id), 5)
            for ally in state.participants
        )
    )


def offensive(
    state: CombatState, actor: CombatParticipant, owner: CombatParticipant, row: dict, loadout: tuple[str, ...]
) -> AbilityDecl | AttackDecl | None:
    weapon = actor.action_pool[0]
    foes = [
        foe
        for foe in state.participants
        if standing_foe(foe) and line_blocker(state, actor.id, foe.id, melee=True) is None
    ]
    foes.sort(key=lambda foe: foe is not owner)
    reachable = [foe for foe in foes if reach_refusal(state, actor, foe.id, weapon) is None]
    if actor.archetype_id == "warrior":
        if affordable(row, loadout, WAR_CRY):
            hearing = set(war_cry_targets(state, actor, WAR_CRY))
            if hearing and not any(
                foe.id in hearing and has_condition(foe.conditions, "frightened") for foe in state.participants
            ):
                return ability(actor, WAR_CRY)
        if affordable(row, loadout, UNSTOPPABLE_CHARGE):
            target = next((foe for foe in foes if not has_condition(foe.conditions, "prone")), None)
            if target is not None:
                return ability(actor, UNSTOPPABLE_CHARGE, target)
        if len(reachable) >= 2 and affordable(row, loadout, WHIRLWIND):
            return ability(actor, WHIRLWIND)
        if len(reachable) >= 2 and affordable(row, loadout, CLEAVING_BLOW):
            return ability(actor, CLEAVING_BLOW, *reachable[:2])
        if owner in foes and affordable(row, loadout, TAUNT) and not has_condition(owner.conditions, "taunted"):
            return ability(actor, TAUNT, owner)
    else:
        if EXPLOIT_WEAKNESS in loadout:
            studied = next((c for c in actor.conditions if c["type"] == STUDIED_WEAKNESS), None)
            if studied is None and foes and affordable(row, loadout, EXPLOIT_WEAKNESS):
                return ability(actor, EXPLOIT_WEAKNESS, foes[0])
            if studied is not None and studied["duration"] == 1:
                target = next(
                    (foe for foe in foes if foe.id == studied["source"] and can_strike(state, actor, foe, weapon)), None
                )
                if target is not None:
                    return weapon_attack(actor, weapon, target)
        if (
            owner in reachable
            and actor.hp_current * 2 < actor.hp_max
            and affordable(row, loadout, DIRTY_TRICK)
            and not has_condition(owner.conditions, "shaken")
        ):
            return ability(actor, DIRTY_TRICK, owner)
        if (
            reachable
            and affordable(row, loadout, BLADE_FLURRY)
            and sneak_attack_opening(state, actor, reachable[0], row)
        ):
            return ability(actor, BLADE_FLURRY, reachable[0])

    for pick in loadout:
        recipe = attack_recipe(pick)
        if recipe is None or not reachable or not affordable(row, loadout, pick):
            continue
        target = reachable[0]
        if pick == CRIPPLING_STRIKE and has_condition(target.conditions, CRIPPLED):
            continue
        if pick == QUICK_FINGERS and target.type != "enemy":
            continue
        rider = recipe["rider"]
        assert isinstance(rider, str)
        return weapon_attack(actor, weapon, target, rider)
    return None
