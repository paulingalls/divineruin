"""Direct healing, attack preparation, and the attack's committed riders."""

import copy

import combat_spatial
import conditions
import dice
import encounter_facts
from combat_condition_landing import _land_condition_on_one
from combat_legendary_resistance import finalize_save, override_fields
from combat_structures import line_blocker
from encounter_actions import action_kind


def healed_hp(current: int, maximum: int, amount: int) -> int:
    return min(maximum, current + max(0, amount))


def heal(actor, amount):
    before = actor.hp_current
    actor.hp_current = healed_hp(before, actor.hp_max, amount)
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
        spatial = combat_spatial.require_spatial(state)
        origin = combat_spatial.position(spatial, actor.id)
        reach = action["reach"]
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
            and combat_spatial.inside(origin, combat_spatial.position(spatial, ally.id), reach)
            and line_blocker(state, actor.id, ally.id) is None
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


def roll_critical_save(state, attacker, target, rider):
    import check_resolution_save

    return check_resolution_save.roll_participant_save(
        target,
        rider["save"],
        rider["dc"],
        rider["applies_condition"],
        dc_mod=attacker.dc_mod,
        combat_state=state,
        bonus_dice_eligible=False,
    )


def land_critical_save(state, attacker, target, action, summary, rider, result):
    condition = rider["applies_condition"]
    can_apply = not already_hollowed(target, condition)
    result = finalize_save(state, target, result, failed_conditions=(condition,) if can_apply else ())
    summary["critical_save"] = {
        "dc": result.dc,
        "roll": result.roll,
        "total": result.total,
        "success": result.success,
        **override_fields(result),
        **encounter_facts.rally_receipt(target.id, result.rally_sources),
    }
    if (
        can_apply
        and not result.success
        and _land_condition_on_one(state, target.id, attacker, condition, source=action["name"], packet=summary)
    ):
        summary["condition_inflicted"] = condition


def apply_critical_save(state, attacker, target, action, summary):
    rider = critical_save_rider(action, summary)
    if rider is not None:
        save = roll_critical_save(state, attacker, target, rider)
        land_critical_save(state, attacker, target, action, summary, rider, save)


def already_hollowed(target, condition):
    return condition == "hollowed" and conditions.has_condition(target.conditions, "hollowed")
