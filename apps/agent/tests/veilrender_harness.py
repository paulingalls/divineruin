"""Shared deterministic Veilrender policy for tuning and tool certification."""

from combat_action_availability import available_actions
from combat_spatial import distance
from declaration_payloads import AbilityDecl, AttackDecl, DefendDecl, Destination, MoveDecl


def declaration(state, actor, victim, cantrip=None):
    assert state.spatial is not None
    positions = state.spatial["positions"]
    origin, target = positions[actor.id], positions[victim.id]
    gap = distance(origin, target)
    if gap > 10 and (actor.type == "enemy" or cantrip is None):
        step = min(state.spatial["speeds"][actor.id] - 0.01, gap - 5) / gap
        return MoveDecl(
            reshape=[],
            movement_mode="ground",
            kind="move",
            nythera_step=False,
            actor_id=actor.id,
            destination=Destination(**{k: float(origin[k] + (target[k] - origin[k]) * step) for k in origin}),
        )
    if actor.type == "enemy":
        actions = available_actions(actor)
        desired = "Reality Crush" if state.round_number % 2 == 0 else "Corruption Pulse"
        action = next((a for a in actions if a["name"] == desired), actions[0])
        if state.round_number == 1:
            return DefendDecl(reshape=[], kind="defend", actor_id=actor.id)
    else:
        if state.round_number == 4:
            return DefendDecl(reshape=[], kind="defend", actor_id=actor.id)
        if cantrip and state.round_number >= 3:
            return AbilityDecl(kind="ability", actor_id=actor.id, action=cantrip, targets=[victim.id], argument_type="")
        action = actor.action_pool[0]
    return AttackDecl(
        reshape=[],
        kind="attack",
        actor_id=actor.id,
        action=action["name"],
        target_id=victim.id,
        held_item_id="",
        rider="",
    )
