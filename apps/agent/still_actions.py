"""Resolve the Still's positional and automatic actions through held packets."""

import math
from functools import partial

import check_resolution_save
import combat_spatial
import conditions
import dice
import encounter_facts
import still_charm
from action_contracts_still import STILL_ZONE_KINDS
from combat_action_availability import begin_execution
from combat_condition_landing import _land_condition_on_one
from combat_damage import apply_attack_result
from combat_damage_results import AutomaticDamageResult
from combat_enemy_action import _save_fields
from combat_fate_rolls import packet_save
from combat_legendary_resistance import finalize_save
from still_encounter import in_zone, zone_radius


def range_refusal(state, actor, action, declaration):
    if action.get("kind") in STILL_ZONE_KINDS:
        return (
            "The Still's zone action takes no declared targets."
            if declaration.target_ids or declaration.target_id
            else None
        )
    target = state.get_participant(declaration.target_id)
    if target is None or target.is_dead or target.is_fallen or target.is_ally == actor.is_ally:
        return "The Still's attack requires a living opposing target."
    if action.get("auto_hit"):
        return None if in_zone(state, actor, target.id) else "Target is outside the Still's zone."
    spatial = combat_spatial.require_spatial(state)
    if not combat_spatial.inside(
        combat_spatial.position(spatial, actor.id), combat_spatial.position(spatial, target.id), action["reach"]
    ):
        return "Target is outside the Still's attack range."
    return None


def zone_edge(state, owner, target_id):
    spatial = combat_spatial.require_spatial(state)
    center = combat_spatial.position(spatial, owner.id)
    origin = combat_spatial.position(spatial, target_id)
    radius = zone_radius(owner)
    distance = combat_spatial.distance(center, origin)
    if distance == 0:
        edge = {**center, "x": center["x"] + radius}
    else:
        edge = {axis: center[axis] + (origin[axis] - center[axis]) * radius / distance for axis in center}
    while not combat_spatial.inside(edge, center, radius):
        edge = {axis: math.nextafter(edge[axis], center[axis]) for axis in center}
    return combat_spatial.force_place(state, target_id, edge)


def _freeze_zone(state, actor, action):
    record = state.still_encounter
    trigger = record["pending_rejection"] if action["kind"] == "rejection" else None
    spatial = combat_spatial.require_spatial(state)
    origin_id = trigger["anchor_id"] if trigger is not None else actor.id
    origin = combat_spatial.position(spatial, origin_id)
    radius = action["radius_ft"] if trigger is not None else zone_radius(actor)
    objects = {actor.id, *record["anchor_ids"]}
    targets = [
        target_id
        for target_id in state.initiative_order
        if target_id not in objects
        and not state.get_participant(target_id).is_dead
        and combat_spatial.inside(origin, combat_spatial.position(spatial, target_id), radius)
    ]
    duration = 1 if trigger is not None else dice.roll(action["duration_dice"]).total
    return {"targets": targets, "trigger": trigger, "duration": duration, "results": []}


async def _save(session, state, target, action, effect, progress, advantage=False):
    return await packet_save(
        progress,
        session,
        target.id,
        effect,
        partial(
            check_resolution_save.roll_participant_save,
            target,
            action["save"],
            action["dc"],
            effect,
            bonus_dice_eligible=False,
            advantage=advantage,
            combat_state=state,
        ),
        state=state,
    )


async def _stun(session, state, actor, target, duration, result, conn, concentration):
    if duration and _land_condition_on_one(
        state, target.id, actor, "stunned", actor.id, packet=result, duration=duration
    ):
        result["stunned_rounds"] = duration
        if target.type == "player":
            broken = await concentration.break_concentration_on_incapacitation(
                session, target.id, combat_state=state, conn=conn
            )
            if broken is not None:
                result["concentration_broken"] = broken


async def _charm(state, actor, target, kind, packet, *, queries, mutations, conn):
    if "charmed" in conditions.get_condition_effects(target.conditions).immunities:
        return False
    landed = _land_condition_on_one(state, target.id, actor, "charmed", actor.id, packet=packet)
    if landed and target.type == "player":
        player = await queries.get_player(target.id, conn=conn, for_update=True)
        if player is None:
            raise ValueError(f"Missing Still charm target {target.id}")
        await still_charm.grant(target.id, player, state.location_id, kind, mutations=mutations, conn=conn)
    return landed


async def resolve_zone(
    session, state, actor, action, declaration, *, head, progress, conn, concentration, queries, mutations
):
    steps = head if head is not None else {}
    if "still_zone" not in steps:
        if action["kind"] == "rejection" and state.still_encounter.get("pending_rejection") is None:
            return {"actor_id": actor.id, "resolved": False, "reason": "No pending anchor attack"}
        steps["still_zone"] = _freeze_zone(state, actor, action)
        begin_execution(state, actor, action, declaration, head)
    execution = steps["still_zone"]
    trigger = execution["trigger"]
    results = execution["results"]
    for target_id in execution["targets"][len(results) :]:
        target = state.get_participant(target_id)
        save = await _save(
            session, state, target, action, "stunned", progress.scope("still_save") if progress is not None else None
        )
        if save is None:
            return {}
        encounter_facts.record_party_attack(state, actor, target)
        duration = execution["duration"]
        if trigger is None:
            failed_conditions = ("stunned", "charmed") if duration else ("charmed",)
            save = finalize_save(state, target, save, failed_conditions=failed_conditions)
        result = {"target_id": target_id, **_save_fields(save, target.id)}
        if trigger is not None and not save.success:
            result.update(zone_edge(state, actor, target_id))
        else:
            if trigger is None and save.success:
                duration //= 2
            await _stun(session, state, actor, target, duration, result, conn, concentration)
            if trigger is None and not save.success:
                result["charmed"] = await _charm(
                    state,
                    actor,
                    target,
                    still_charm.FINAL_STILLNESS,
                    result,
                    queries=queries,
                    mutations=mutations,
                    conn=conn,
                )
        results.append(result)
        if progress is not None:
            progress.steps.pop("still_save", None)
    summary = {"actor_id": actor.id, "resolved": True, "action": action["name"], "targets": results}
    if trigger is not None:
        record = state.still_encounter
        if record["pending_rejection"] == trigger:
            record["pending_rejection"] = None
        summary["origin_anchor_id"] = trigger["anchor_id"]
    return summary


async def resolve_touch(
    session,
    state,
    actor,
    action,
    declaration,
    *,
    head,
    progress,
    conn,
    mutations,
    queries,
    concentration,
    sink,
    advantage,
):
    target = state.get_participant(declaration.target_id)
    steps = head if head is not None else {}
    if "still_touch" not in steps:
        begin_execution(state, actor, action, declaration, head)
        steps["still_touch"] = {"damage": dice.roll(action["damage"]).total}
    receipt = steps["still_touch"]
    if "landed" not in receipt:
        damage = AutomaticDamageResult(receipt["damage"], action["damage_type"], context="still_touch")
        landed = await apply_attack_result(
            session,
            actor,
            action,
            target,
            damage,
            target.ac,
            combat_state=state,
            conn=conn,
            mutations=mutations,
            queries=queries,
            concentration_break_mod=concentration,
            sink=sink,
            publish_roll=False,
            progress=progress.scope("still_damage") if progress is not None else None,
        )
        if progress is not None and progress.paused:
            return {}
        receipt["landed"] = landed
    summary = {**receipt["landed"], "actor_id": actor.id, "resolved": True, "action": action["name"]}
    if not target.is_fallen:
        save = await _save(
            session,
            state,
            target,
            action,
            "charmed",
            progress.scope("still_save") if progress is not None else None,
            advantage,
        )
        if save is None:
            return {}
        save = finalize_save(state, target, save, failed_conditions=("charmed",))
        summary.update(_save_fields(save, target.id))
        if not save.success:
            summary["charmed"] = await _charm(
                state,
                actor,
                target,
                still_charm.SERENITYS_TOUCH,
                summary,
                queries=queries,
                mutations=mutations,
                conn=conn,
            )
    return summary
