"""Resolve the Marshal's Reposition order in the Marshal's initiative slot."""

import abilities
import combat_ally_pass
import combat_martial
import combat_spatial_declarations as moves
from combat_ability_gate import REPOSITION_FEET, DeclaredAbility
from combat_participant import CombatParticipant
from combat_state import CombatState
from condition_sources import DeliveryRefused
from declarations import Declaration, DeclarationType
from patron_synergy_combat import grant_marshal_rally


def validate_route(
    state: CombatState, actor: CombatParticipant, decl: Declaration, ability: abilities.Ability
) -> tuple[CombatParticipant, Declaration]:
    (ally_id,), _ = combat_martial.order_recipients(state, actor, decl, ability)
    ally = state.get_participant(ally_id)
    assert ally is not None
    if reason := moves.ineligible(ally):
        raise moves.MovementRefused(reason)
    leg = Declaration(type=DeclarationType.MANEUVER, action="move", target_id=ally.id, destination=decl.destination)
    moves.movement_geometry(state, ally.id, leg, allowance=REPOSITION_FEET, hard_limit=True)
    return ally, leg


async def resolve(
    state: CombatState, actor: CombatParticipant, decl: Declaration, resolved: DeclaredAbility, *, conn, queries
) -> dict:
    try:
        ally, leg = validate_route(state, actor, decl, resolved[0])
    except (DeliveryRefused, moves.MovementRefused) as error:
        return {
            **combat_martial.order_receipt(actor, decl, resolved, None, effect_resolution="engine"),
            "resolved": False,
            "reason": str(error),
            "deducted": {"focus": 0, "stamina": 0},
        }

    movement = moves.apply_move(state, ally, leg, allowance=REPOSITION_FEET)
    assert movement["resolved"], movement
    await combat_martial.pay(actor.id, resolved, queries=queries, conn=conn)
    grant = await grant_marshal_rally(state, actor.id, ally.id, queries=queries, conn=conn)
    destination = movement["destination"]
    stopped = movement.get("left_pit", False)
    cancelled = combat_ally_pass.cancel_queued_move(state, ally.id)
    point = f"{destination['x']:g}, {destination['y']:g}, {destination['z']:g}"
    cue = (
        f"{ally.name} climbs out of the pit and stops at {point}."
        if stopped
        else f"Reposition moves {ally.name} to {point}."
    )
    if cancelled:
        cue += f" {ally.name}'s queued move is cancelled."
    return {
        **combat_martial.order_receipt(actor, decl, resolved, grant, effect_resolution="engine"),
        "destination": destination,
        "moved_ft": movement["moved_ft"],
        "movement_spent_ft": movement["movement_spent_ft"],
        **({"left_pit": True, "reason": "Stopped after climbing out of the pit."} if stopped else {}),
        **({"cancelled_move": ally.id} if cancelled else {}),
        "dm_cue": cue,
    }
