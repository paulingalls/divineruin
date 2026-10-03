"""Structured Choir targets use the committed combat geometry."""

from dataclasses import replace

import combat_spatial
from combat_enemy_action import resolve_save_damage_action


def require_targets(state, actor, action, declaration):
    spatial = combat_spatial.require_spatial(state)
    origin = combat_spatial.position(spatial, actor.id)
    if action.get("type") == "area":
        return [
            p
            for p in state.participants
            if not p.is_fallen
            and not p.is_dead
            and combat_spatial.inside(origin, combat_spatial.position(spatial, p.id), action["reach"])
        ]
    target = state.get_participant(declaration.target_id)
    if target is None:
        raise ValueError("Choir action requires a known participant target")
    if not combat_spatial.inside(origin, combat_spatial.position(spatial, target.id), action["reach"]):
        raise ValueError("Choir target is outside the authored range")
    return [target]


async def resolve_area(session, state, actor, action, declaration, **deps):
    results = []
    for target in require_targets(state, actor, action, declaration):
        result = await resolve_save_damage_action(
            session, actor, replace(declaration, target_id=target.id), action, state=state, **deps
        )
        results.append({"target_id": target.id, **result})
    return {"actor_id": actor.id, "resolved": True, "action": action["name"], "targets": results}


async def resolve_effect(session, state, actor, action, declaration, *, reaction_save_advantage=False):
    import check_resolution_save
    from choir_effects import inflict_silence
    from combat_action_availability import begin_execution
    from combat_condition_landing import _land_condition_on_one
    from condition_sources import DeliveryRefused
    from condition_voice_rules import no_spoken_buffs
    from dice import roll
    from spell_voice_rules import require_speech

    require_speech(state, actor.id)
    target = state.get_participant(declaration.target_id or actor.id)
    if target is None:
        raise ValueError("Choir effect requires a known participant")
    if action["kind"] == "silence":
        begin_execution(state, actor, action, declaration)
        return inflict_silence(state, actor, action, declaration)
    if no_spoken_buffs(target.conditions, state=state, actor_id=target.id):
        raise DeliveryRefused("Melody target cannot hear the voice")
    begin_execution(state, actor, action, declaration)
    save = check_resolution_save.roll_participant_save(
        target, action["save"], action["dc"], "charmed", bonus_dice_eligible=False, advantage=reaction_save_advantage
    )
    result = {"actor_id": actor.id, "resolved": True, "save_success": save.success}
    if reaction_save_advantage and save.advantage_applied:
        result["save_advantage"] = True
    if not save.success:
        duration = roll(action["duration_dice"]).total
        landed = _land_condition_on_one(state, target.id, actor, "charmed", actor.id, packet=result, duration=duration)
        if landed:
            for condition in target.conditions:
                if condition["type"] == "charmed":
                    condition["choir_melody"] = True
            result.update(condition_inflicted="charmed", duration=duration)
    return result
