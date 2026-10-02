"""The executable action surface shared by declaration validation and the roster."""

from combat_recharge import available, initialize
from encounter_actions import action_kind


def available_actions(actor):
    initialize(actor)
    return [action for action in actor.action_pool if available(actor, action)]


def action_summary(actor):
    actions = available_actions(actor)
    return {
        "actions": [a["name"] for a in actions],
        "mark_actions": [
            {"name": a["name"], "kind": action_kind(a)} for a in actions if action_kind(a) in ("command", "accusation")
        ],
        "executable_actions": [
            {
                "name": a["name"],
                "kind": action_kind(a),
                "declaration_type": "ability" if action_kind(a) in ("healing", "prepare_attack") else "attack",
            }
            for a in actions
        ],
    }


def require_available(actor, action):
    if not available(actor, action):
        raise ValueError(
            f"{actor.id}: action {action['name']!r} unavailable; available actions: {action_summary(actor)['actions']}"
        )


def replay_valid(state, head, actor, action, declaration):
    return (
        bool(state.held_actions)
        and head is state.held_actions[0]
        and head.get("execution_receipt")
        == {
            "id": head.get("execution_id"),
            "actor_id": actor.id,
            "action": action["name"].casefold(),
            "target_id": declaration.target_id,
            "round": state.round_number,
        }
        and head.get("execution_id") is not None
        and actor.last_action_execution == head["execution_receipt"]
    )


def begin_execution(state, actor, action, declaration, head=None):
    from uuid import uuid4

    from combat_recharge import spend

    spend(actor, action, state.round_number)
    executed = dict(action)
    attack_roll = (
        action_kind(action) == "attack"
        and not action.get("half_on_success")
        and (not action.get("applies_condition") or action.get("damage") not in (None, "", "0", 0))
    )
    if attack_roll and actor.pending_preparation is not None:
        executed["advantage"] = True
        executed["prepared_on_hit"] = actor.pending_preparation["on_hit"]
        actor.pending_preparation = None
    if head is not None and "execution_id" not in head:
        head["execution_id"] = uuid4().hex
    receipt = {
        "id": head["execution_id"] if head is not None else uuid4().hex,
        "actor_id": actor.id,
        "action": action["name"].casefold(),
        "target_id": declaration.target_id,
        "round": state.round_number,
    }
    actor.last_action_execution = receipt
    if head is not None:
        head["execution_receipt"] = receipt
        head["executed_action"] = executed
    return executed
