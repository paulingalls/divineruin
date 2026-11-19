"""Direct healing, attack preparation, and the attack's committed riders."""

import copy

import conditions
import dice
from combat_condition_landing import _land_condition_on_one
from encounter_actions import action_kind


def heal(actor, amount):
    before = actor.hp_current
    actor.hp_current = min(actor.hp_max, before + max(0, amount))
    return actor.hp_current - before


def resolve_active(state, actor, action, declaration):
    summary = {
        "actor_id": actor.id,
        "resolved": True,
        "action": action["name"],
        "declaration_type": str(declaration.type),
    }
    kind = action_kind(action)
    if kind == "prepare_attack":
        actor.pending_preparation = {"on_hit": copy.deepcopy(action["on_hit"])}
        summary["prepared_attack"] = True
    elif kind == "healing":
        amount = dice.roll(action["healing"]).total
        summary["healed"] = {
            ally.id: heal(ally, amount)
            for ally in state.participants
            if ally.type == "enemy"
            and ally.is_ally == actor.is_ally
            and ally.creature_id in ("bandit", "bandit_captain")
            and not ally.is_fallen
            and not ally.is_dead
            and ally.hp_current > 0
        }
    else:
        raise ValueError(f"{action['name']}: unsupported active kind {kind}")
    return summary


def apply_prepared_hit(state, attacker, target, action, summary):
    rider = action.get("prepared_on_hit")
    if rider is None or not summary.get("hit"):
        return
    if "damage" in rider:
        attacker.pending_preparation = None
        return
    if target.is_fallen:
        return
    condition = rider["applies_condition"]
    if _land_condition_on_one(
        state, target.id, attacker, condition, source=action["name"], duration=rider["duration"], packet=summary
    ):
        summary["condition_inflicted"] = condition
    else:
        summary["condition_immune"] = condition


def critical_save_rider(action, summary):
    """The attack's on-crit save rider, when this landed blow is a critical hit."""
    rider = action.get("critical_save")
    if rider is None or not summary.get("hit") or not summary.get("critical"):
        return None
    return rider


def roll_critical_save(attacker, target, rider):
    import check_resolution_save

    return check_resolution_save.roll_participant_save(
        target,
        rider["save"],
        rider["dc"],
        rider["applies_condition"],
        dc_mod=attacker.dc_mod,
        bonus_dice_eligible=False,
    )


def land_critical_save(state, attacker, target, action, summary, rider, result):
    summary["critical_save"] = {"dc": result.dc, "roll": result.roll, "total": result.total, "success": result.success}
    if already_hollowed(target, rider["applies_condition"]):
        return
    if not result.success and _land_condition_on_one(
        state, target.id, attacker, rider["applies_condition"], source=action["name"], packet=summary
    ):
        summary["condition_inflicted"] = rider["applies_condition"]


def apply_critical_save(state, attacker, target, action, summary):
    rider = critical_save_rider(action, summary)
    if rider is not None:
        land_critical_save(state, attacker, target, action, summary, rider, roll_critical_save(attacker, target, rider))


def already_hollowed(target, condition):
    return condition == "hollowed" and conditions.has_condition(target.conditions, "hollowed")
