"""Encounter-specific action kinds that resolve without the shared weapon roll.

The Still's range gate, zone and touch; the Architect's constructs; a hostile heal or
prepared attack; and the Choir's charm and silence each own a resolver. ``resolve``
returns that resolver's summary, or None when the action is an ordinary strike that
the packet resolver (combat_packet) carries on to approach, roll and damage."""

import architect_constructs
from action_contracts_still import STILL_ZONE_KINDS
from combat_action_availability import begin_execution
from combat_enemy_active import resolve_active
from encounter_actions import action_kind


async def resolve(
    session,
    state,
    attacker,
    action: dict,
    decl,
    *,
    replay: bool,
    head,
    progress,
    conn,
    mutations,
    queries,
    concentration_break_mod,
    sink,
    reaction_save_advantage: bool,
    psychic_shield_id: str | None = None,
) -> dict | None:
    import still_encounter

    if still_encounter.is_owner(state, attacker.id):
        import still_actions

        if not replay and (reason := still_actions.range_refusal(state, attacker, action, decl)):
            return {"actor_id": attacker.id, "resolved": False, "reason": reason}
        if action_kind(action) in STILL_ZONE_KINDS:
            return await still_actions.resolve_zone(
                session,
                state,
                attacker,
                action,
                decl,
                head=head,
                progress=progress,
                conn=conn,
                concentration=concentration_break_mod,
                queries=queries,
                mutations=mutations,
            )
        if action.get("auto_hit"):
            return await still_actions.resolve_touch(
                session,
                state,
                attacker,
                action,
                decl,
                head=head,
                progress=progress,
                conn=conn,
                mutations=mutations,
                queries=queries,
                concentration=concentration_break_mod,
                sink=sink,
                psychic_shield_id=psychic_shield_id,
                advantage=reaction_save_advantage,
            )
    if action_kind(action) == architect_constructs.KIND:
        return architect_constructs.resolve(state, attacker, action, decl)
    if not attacker.is_ally and action_kind(action) in ("healing", "prepare_attack"):
        return resolve_active(state, attacker, begin_execution(state, attacker, action, decl), decl)
    if action_kind(action) in ("charm", "silence"):
        from choir_actions import resolve_effect

        return await resolve_effect(
            session,
            state,
            attacker,
            action,
            decl,
            reaction_save_advantage=reaction_save_advantage,
            progress=progress,
            head=head,
        )
    return None
