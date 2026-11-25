"""Structured Choir targets use the committed combat geometry."""

from dataclasses import replace
from functools import partial

import combat_spatial
import encounter_facts
from combat_enemy_action import resolve_save_damage_action
from combat_fate_rolls import packet_save
from combat_legendary_resistance import finalize_save, override_fields
from combat_structures import blocking_wall


def require_targets(state, actor, action, declaration):
    spatial = combat_spatial.require_spatial(state)
    origin = combat_spatial.position(spatial, actor.id)
    if action.get("type") == "area":
        aim = combat_spatial.position(spatial, declaration.target_id) if action.get("shape") == "cone" else None
        if aim is not None:
            combat_spatial.axis_projection(origin, aim, origin)
        return [
            p
            for p in state.participants
            if p.id != actor.id
            and not p.is_fallen
            and not p.is_dead
            and (
                combat_spatial.in_cone(origin, aim, combat_spatial.position(spatial, p.id), action["reach"])
                if aim is not None
                else combat_spatial.inside(origin, combat_spatial.position(spatial, p.id), action["reach"])
            )
            and blocking_wall(state, spatial, origin, combat_spatial.position(spatial, p.id), target_id=p.id) is None
        ]
    target = state.get_participant(declaration.target_id)
    if target is None:
        raise ValueError("Choir action requires a known participant target")
    if not combat_spatial.inside(origin, combat_spatial.position(spatial, target.id), action["reach"]):
        raise ValueError("Choir target is outside the authored range")
    return [target]


async def resolve_area(session, state, actor, action, declaration, *, progress=None, head=None, **deps):
    from architect_actions import is_cathedral, raise_cathedral
    from combat_action_availability import begin_execution

    deps.setdefault("reaction_save_advantage", False)
    steps = progress.steps if progress is not None else {}
    if "targets" not in steps:
        if is_cathedral(state, actor.id, action):
            action = begin_execution(state, actor, action, declaration, head)
            steps["targets"] = raise_cathedral(state, actor.id)
        else:
            steps["targets"] = [target.id for target in require_targets(state, actor, action, declaration)]
            action = begin_execution(state, actor, action, declaration, head)
        steps["results"] = []
    results = steps["results"]
    for target_id in steps["targets"][len(results) :]:
        result = await resolve_save_damage_action(
            session,
            actor,
            replace(declaration, target_id=target_id),
            action,
            state=state,
            progress=progress.scope("target") if progress is not None else None,
            **deps,
        )
        if progress is not None:
            if progress.paused:
                return {}
            steps.pop("target", None)
        results.append({"target_id": target_id, **result})
    return {"actor_id": actor.id, "resolved": True, "action": action["name"], "targets": results}


async def resolve_effect(
    session, state, actor, action, declaration, *, reaction_save_advantage=False, progress=None, head=None
):
    import check_resolution_save
    from choir_effects import inflict_silence
    from combat_action_availability import begin_execution
    from combat_condition_landing import _land_condition_on_one
    from dice import roll
    from spell_voice_rules import require_speech

    require_speech(state, actor.id)
    target = state.get_participant(declaration.target_id or actor.id)
    if target is None:
        raise ValueError("Choir effect requires a known participant")
    if action["kind"] == "silence":
        begin_execution(state, actor, action, declaration)
        return inflict_silence(state, actor, action, declaration)
    if target.is_fallen or target.is_dead:
        return {"actor_id": actor.id, "resolved": False, "reason": "Melody target unavailable"}
    if head is None or "execution_receipt" not in head:
        begin_execution(state, actor, action, declaration, head)
    save = await packet_save(
        progress,
        session,
        target.id,
        "charmed",
        partial(
            check_resolution_save.roll_participant_save,
            target,
            action["save"],
            action["dc"],
            "charmed",
            bonus_dice_eligible=False,
            advantage=reaction_save_advantage,
        ),
    )
    if save is None:
        return {}
    encounter_facts.record_party_attack(state, actor, target)
    if not save.success:
        duration = roll(action["duration_dice"]).total
        save = finalize_save(state, target, save, failed_conditions=("charmed",) if duration else ())
    else:
        duration = 0
    result = {"actor_id": actor.id, "resolved": True, "save_success": save.success, **override_fields(save)}
    if reaction_save_advantage and save.advantage_applied:
        result["save_advantage"] = True
    if not save.success:
        landed = _land_condition_on_one(state, target.id, actor, "charmed", actor.id, packet=result, duration=duration)
        if landed:
            for condition in target.conditions:
                if condition["type"] == "charmed":
                    condition["choir_melody"] = True
            result.update(condition_inflicted="charmed", duration=duration)
    return result
