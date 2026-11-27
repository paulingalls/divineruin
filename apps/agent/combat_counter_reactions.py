"""Settle counters on the held enemy strike that provoked them."""

from typing import TYPE_CHECKING

import combat_melee_approach as melee
import combat_spatial_declarations as movement
import dice
from combat_damage_results import AutomaticDamageResult
from combat_durability import _find_equipped
from combat_enhancers import SHIELD_BASH_ACTION
from combat_fate_rolls import PacketRolls, PhaseRolls
from combat_spatial import inside, point, position, require_spatial
from combat_structures import blocked_reason, line_blocker
from declarations import Declaration, DeclarationType
from reaction_spend import RETALIATE, RIPOSTE
from rules_engine import attribute_modifier

if TYPE_CHECKING:
    from combat_participant import CombatParticipant
    from combat_state import CombatState
    from session_data import SessionData

SIDESTEP_CUE = "Supply destination {x,y,z} within 5 feet. The step does not provoke. The attack can still reach you."


def validate_weapon(state: "CombatState", reactor_id: str, enemy_id: str, weapon: dict | None) -> None:
    if weapon is None or not melee.is_melee(weapon):
        raise ValueError("Riposte requires an equipped melee weapon.")
    spatial = require_spatial(state)
    if not inside(position(spatial, reactor_id), position(spatial, enemy_id), melee.melee_reach(weapon)):
        raise ValueError("The attacker is beyond Riposte's melee reach.")
    if blocker := line_blocker(state, reactor_id, enemy_id, melee=True):
        raise ValueError(blocked_reason(blocker))


async def prepare_equipment(state: "CombatState", actor_id: str, player: dict, spend: dict, *, queries, conn) -> None:
    if spend["ability_id"] == RETALIATE:
        inventory = await queries.get_player_inventory(actor_id, conn=conn)
        if _find_equipped(inventory, "shield") is None:
            raise ValueError("Retaliating Shield requires an equipped shield.")
    if spend["ability_id"] == RIPOSTE:
        weapon = player.get("equipment", {}).get("main_hand")
        validate_weapon(state, actor_id, state.held_actions[0]["actor_id"], weapon)
        spend["weapon"] = weapon


def sidestep_declaration(state: "CombatState", actor: "CombatParticipant", destination: dict | None) -> Declaration:
    if destination is None:
        raise ValueError("Sidestep requires a destination point within 5 feet.")
    destination = point(destination)
    if reason := movement.ineligible(actor):
        raise ValueError(reason)
    if movement.in_pit(state, actor.id):
        raise ValueError("Sidestep cannot climb out of a pit.")
    spatial = require_spatial(state)
    if any(
        other.id != actor.id and not other.is_dead and position(spatial, other.id) == destination
        for other in state.participants
        if other.id in spatial["positions"]
    ):
        raise ValueError("Sidestep destination is occupied.")
    declaration = Declaration(DeclarationType.MANEUVER, "move", target_id=actor.id, destination=destination)
    movement.movement_geometry(state, actor.id, declaration, allowance=5, hard_limit=True)
    return declaration


def _progress(session: "SessionData", continuation: dict, deps: dict, fate: PhaseRolls | None) -> PacketRolls | None:
    if fate is not None and (session.fate_lock.locked() or "steps" in continuation):
        return PacketRolls(fate, continuation.setdefault("steps", {}), deps["queries"], deps["conn"])
    return None


async def sidestep(
    session: "SessionData",
    state: "CombatState",
    head: dict,
    action: dict,
    deps: dict,
    fate: PhaseRolls | None,
) -> dict | None:
    pending = head["sidestep"]
    packet = pending["packet"]
    actor = state.get_participant(packet["actor_id"])
    assert actor is not None
    destination = pending["destination"]
    progress = _progress(session, pending, deps, fate)
    try:
        if progress is not None and "hearthfire_move" in progress.steps:
            declaration = Declaration(DeclarationType.MANEUVER, "move", target_id=actor.id, destination=destination)
        else:
            declaration = sidestep_declaration(state, actor, destination)
    except ValueError as error:
        return {**packet, "reason": str(error)}

    # Traversal handles the terrain and Hearthfire leg. Opportunity attacks live in the ordinary
    # player-movement wrapper, which this unprovoking step deliberately bypasses.
    facts = await movement.resolve_traversal(
        session, state, actor, declaration, allowance=5, hard_limit=True, progress=progress
    )
    if facts is None:
        return None
    spatial = require_spatial(state)
    escaped = not inside(position(spatial, head["actor_id"]), position(spatial, actor.id), melee.melee_reach(action))
    head["sidestep_escaped"] = escaped
    reach = (
        "The attack misses because you stepped out of reach." if escaped else "You are still within the attack's reach."
    )
    return {
        **packet,
        "mechanical_effect": "sidestep" if facts["moved_ft"] else None,
        "movement": facts,
        "reason": f"{facts['reason']} {reach}" if "reason" in facts else reach,
    }


async def settle(
    session: "SessionData", state: "CombatState", head: dict, summaries: list[dict], deps: dict, fate: PhaseRolls | None
) -> bool:
    from combat_damage import apply_attack_result
    from combat_opportunity import counter_strike

    target = state.get_participant(head["actor_id"])
    assert target is not None
    continuation = head["counter_settlement"]
    queue = continuation["packets"]
    while queue:
        packet = queue[0]
        ability = packet["ability_id"]
        counter = continuation.setdefault("counter", {})
        actor = state.get_participant(packet["actor_id"])
        assert actor is not None
        if ability == RETALIATE and continuation["attack"].get("hit"):
            progress = _progress(session, counter, deps, fate)
            kind = SHIELD_BASH_ACTION["damage_type"]
            result = None
            if progress is None or "damage_receipt" not in progress.steps:
                damage = max(0, dice.roll("1d6").total + attribute_modifier(actor.attributes["strength"]))
                result = AutomaticDamageResult(damage, kind, "Retaliating Shield strikes back.", context="")
            receipt = await apply_attack_result(
                session,
                actor,
                {"name": packet["ability_name"], "damage_type": kind},
                target,
                result,
                target.ac,
                publish_roll=False,
                combat_state=state,
                progress=progress,
                **{key: deps[key] for key in ("queries", "mutations", "concentration_break_mod", "conn", "sink")},
            )
            if fate is not None and fate.pending is not None:
                return False
            packet["counter_attack"] = {
                **receipt,
                "actor_id": actor.id,
                "target_id": target.id,
                "reaction": ability,
                "window_id": packet["window_id"],
            }
        elif ability == RIPOSTE:
            spend = state.reactions_available[actor.id]
            if "weapon" in spend:
                counter.update(actor_id=actor.id, ability_id=ability, window_id=packet["window_id"])
                receipt = await counter_strike(session, state, target, spend["weapon"], counter, deps, fate)
                if fate is not None and fate.pending is not None:
                    return False
                packet.update(mechanical_effect="riposte", counter_attack=receipt)
        summaries.append(queue.pop(0))
        continuation.pop("counter")
    return True
