"""Per-packet/phase resolution helpers for the combat phase loop (split from
combat_turn.py to keep that file under the 500-line ceiling).

resolve_phase (in combat_turn) orchestrates the per-phase transaction; the
helpers here do the actual resolution work it drives: _prevalidate_ability_focus
gates player ability Focus before the loop, _resolve_one_packet dispatches a
single initiative-ordered packet to the right resolver (attack / ability /
de-escalate / defend). The helpers mutate in-memory
state and write through injected mutation/query modules, but own no transaction."""

import combat_fate
import combat_maneuver
import combat_marks
import combat_melee_approach
import combat_recharge
import combat_spatial_declarations
import combat_voice_rules
import spell_casting
from action_contracts_still import STILL_ZONE_KINDS
from combat_ability import (
    AbilityCastOutcome,
    _attach_riders,
    _find_action,
    _resolve_ability_condition_packet,
    _resolve_ability_packet,
    condition_ability,
)
from combat_ability_gate import declared_ability
from combat_action_availability import begin_execution, replay_valid
from combat_deescalation import (
    _resolve_deescalation_packet,
)
from combat_down import target_unavailable
from combat_enemy_action import resolve_enemy_strike
from combat_enemy_active import resolve_active
from combat_packet_gate import _prevalidate_ability_focus as _prevalidate_ability_focus
from condition_restrictions import cannot_act
from condition_sources import DeliveryRefused
from declarations import DeclarationType
from encounter_actions import action_kind
from session_data import SessionData


async def _resolve_one_packet(session, state, packet, **deps) -> dict:
    from combat_veilrender import turn_start

    progress = deps.get("progress")
    steps = progress.steps if progress is not None else {}
    # Turn-start effects run once per round; a Zhael-held packet keeps them for its resumed summary.
    effects = steps.pop("turn_start_effects", None)
    if not effects:
        effects = await turn_start(
            session,
            state,
            state.get_participant(packet.actor_id),
            **{**deps, "progress": progress.scope("veilrender") if progress is not None else None},
        )
        if effects is None:
            return {}
    result = await _resolve_action_packet(session, state, packet, **deps)
    if progress is not None and progress.paused:
        if effects:
            attack_cursor = deps.get("attack_cursor")
            (attack_cursor if attack_cursor else steps)["turn_start_effects"] = effects
        return result
    if effects:
        result["turn_start_effects"] = effects
    return result


async def _resolve_action_packet(
    session: SessionData,
    state,
    packet,
    *,
    mutations,
    queries,
    resolver,
    concentration_break_mod,
    conn=None,
    sink=None,
    cast_resolver=spell_casting,
    cast_outcome=None,
    players_by_id=None,
    reaction_ac_bonus: int = 0,
    reaction_save_advantage: bool = False,
    shield_reaction: str | None = None,
    grapple_blocked: bool = False,
    mark_cancelled: bool = False,
    publish_roll: bool = True,
    _held_head=None,
    _melee_approach=None,
    attack_cursor=None,
    progress=None,
) -> dict:
    """Resolve a single initiative-ordered ResolutionPacket against ``state``.

    A declaration is *wasted* (resolved=False) when its actor or target is gone or
    has already fallen this phase, or its action isn't in the actor's pool — one bad
    or stale declaration never crashes the phase. Attack resolves through the shared
    attack resolver (carrying the target's phase AC modifier) and records the player's
    weapon-durability flags. Ability resolves through the shared cast logic (story-007,
    via _resolve_ability_packet), its CastResult stashed on ``cast_outcome`` for the
    phase loop to commit. Defend resolves as a no-op (its +2 AC was applied to
    state.ac_modifiers in the resolve_phase pre-pass). Maneuver resolves as stand or shove;

    ``reaction_ac_bonus`` is the Beat-3 hold's channel for a pre-roll reaction's +2 AC against the
    ONE held blow it was spent against (story-018), and ``shield_reaction`` the same channel for a
    post-roll shield-bearing one; 0/None on every unpaused path. ``publish_roll`` is False only
    for a held attack whose DICE_ROLL was already announced at its POST_ROLL pause."""
    attacker = state.get_participant(packet.actor_id)
    decl = packet.declaration
    if decl.type is DeclarationType.MULTIATTACK:
        raise ValueError("multiattack must expand into held strikes before resolution")
    # This actor's own pre-validated for_update row (M14 story-004): the ability branches below thread
    # it to the cast/deduct so a non-primary caster's Focus/Resonance land on ITS pool. None for a
    # non-caster packet (attack/defend) or an actor with no player ability — those branches ignore it.
    player = players_by_id.get(packet.actor_id) if players_by_id else None

    import choir_encounter
    import still_encounter

    still_encounter.guard_declaration(state, packet.actor_id, decl)

    stale = choir_encounter.stale_reason(state, packet.actor_id, decl)
    if stale is None:
        choir_encounter.guard_declaration(state, packet.actor_id, decl)

    await choir_encounter.turn_start(
        session,
        state,
        attacker,
        conn=conn,
        concentration_break_mod=concentration_break_mod,
        sink=sink,
        progress=progress.scope("choir_aura") if progress is not None else None,
    )
    if progress is not None and progress.paused:
        return {}

    from choir_effects import approach

    forced_move = approach(state, attacker)
    if attacker is None or attacker.is_fallen:
        return {"actor_id": packet.actor_id, "resolved": False, "reason": "actor unavailable"}
    if blocked := cannot_act(attacker.conditions):
        reason = f"{attacker.name} is {blocked[0]} and loses the phase"
        return {"actor_id": packet.actor_id, "resolved": False, "reason": reason}

    if combat_spatial_declarations.is_move(decl) and forced_move is not None:
        return forced_move
    if combat_spatial_declarations.is_move(decl):
        return combat_spatial_declarations.apply_move(state, attacker, decl)

    if stale is not None:
        return {"actor_id": packet.actor_id, "resolved": False, "reason": stale}

    try:
        combat_voice_rules.guard_declaration(state, attacker, decl)
    except DeliveryRefused as e:
        return {"actor_id": attacker.id, "resolved": False, "reason": str(e)}

    if decl.type is DeclarationType.INTERACT and decl.action in choir_encounter.SEARCH_ACTIONS:
        return await choir_encounter.search(
            session,
            state,
            attacker,
            decl,
            queries=queries,
            conn=conn,
            progress=progress.scope("choir_search") if progress is not None else None,
        )

    if decl.type is DeclarationType.INTERACT and decl.action in still_encounter.SEARCH_ACTIONS:
        return await still_encounter.search(
            session,
            state,
            attacker,
            decl,
            queries=queries,
            conn=conn,
            progress=progress.scope("still_search") if progress is not None else None,
        )

    if decl.type is DeclarationType.DEFEND:
        return {
            "actor_id": packet.actor_id,
            "resolved": True,
            "declaration_type": str(decl.type),
            "ac_bonus": decl.ac_bonus,
        }

    action = (
        _find_action(attacker, decl.action)
        if decl.type is DeclarationType.ATTACK or (not attacker.is_ally and decl.type is DeclarationType.ABILITY)
        else None
    )

    movement = {}
    movement_budget = {}
    if action is not None:
        replay = _held_head is not None and replay_valid(state, _held_head, attacker, action, decl)
        pending_execution = any(
            head.get("actor_id") == attacker.id and head.get("execution_receipt") is not None
            for head in state.held_actions
        )
        if (
            (_held_head is not None and _held_head.get("execution_receipt") is not None and not replay)
            or (_held_head is None and pending_execution)
            or (not replay and not combat_recharge.available(attacker, action))
        ):
            return {"actor_id": attacker.id, "resolved": False, "reason": "action unavailable"}
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
                    head=_held_head,
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
                    head=_held_head,
                    progress=progress,
                    conn=conn,
                    mutations=mutations,
                    queries=queries,
                    concentration=concentration_break_mod,
                    sink=sink,
                    advantage=reaction_save_advantage,
                )
        if not attacker.is_ally and action_kind(action) in ("healing", "prepare_attack"):
            action = begin_execution(state, attacker, action, decl)
            return resolve_active(state, attacker, action, decl)
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
                head=_held_head,
            )
        target = state.get_participant(decl.target_id) if decl.target_id else None
        if target is not None and not target_unavailable(target, action):
            # Move before any roll is prepared, and only once: a held head carries its approach, and a
            # Zhael-held ally swing resumes through its attack cursor, never back through here.
            if _melee_approach is not None:
                movement = _melee_approach
            else:
                movement = combat_melee_approach.prepare(state, attacker, target, action, movement_budget)
            if movement.get("attack_resolved") is False:
                return movement
        if replay:
            assert _held_head is not None
            action = _held_head["executed_action"]
        elif (
            target is not None
            and not target_unavailable(target, action)
            and not (
                (action.get("resolution") == "save" or action.get("shape") == "cone") and action.get("type") == "area"
            )
            and (
                decl.type is DeclarationType.ATTACK
                or action.get("applies_condition")
                or action.get("half_on_success") is True
            )
        ):
            action = begin_execution(state, attacker, action, decl, _held_head)

    if (
        not attacker.is_ally
        and action is not None
        and (action.get("resolution") == "save" or action.get("shape") == "cone")
        and action.get("type") == "area"
    ):
        from choir_actions import resolve_area

        return await resolve_area(
            session,
            state,
            attacker,
            action,
            decl,
            conn=conn,
            mutations=mutations,
            queries=queries,
            concentration_break_mod=concentration_break_mod,
            sink=sink,
            reaction_save_advantage=reaction_save_advantage,
            progress=progress,
            head=_held_head,
        )
    if not attacker.is_ally and action is not None:
        enemy_summary = await resolve_enemy_strike(
            session,
            attacker,
            decl,
            action,
            state=state,
            packet=packet,
            conn=conn,
            mutations=mutations,
            queries=queries,
            resolver=resolver,
            concentration_break_mod=concentration_break_mod,
            sink=sink,
            reaction_ac_bonus=reaction_ac_bonus,
            shield_reaction=shield_reaction,
            reaction_save_advantage=reaction_save_advantage,
            progress=progress,
            publish_roll=publish_roll,
        )
        if enemy_summary is not None:
            return {**movement, **enemy_summary}

    if decl.type is DeclarationType.ABILITY:
        # (Enemy condition-infliction ABILITY is handled by the type-agnostic branch above, which
        # routes both ATTACK and ABILITY enemy actions carrying applies_condition. The branches
        # below are the player-oriented paths.)
        # De-escalate (M4.6a story-004) is an ABILITY but resolves socially, not as a cast:
        # contested gate + one argument that can end combat. Its Focus/lockout were pre-gated
        # in _prevalidate_ability_focus, and ``player`` is the for_update row from there.
        if (decl.action or "").lower() == "de_escalate":
            return await _resolve_deescalation_packet(
                session,
                attacker,
                decl,
                state=state,
                conn=conn,
                player=player,
                sink=sink,
                progress=progress.scope("deescalation") if progress is not None else None,
            )
        # A non-spell condition ability (M4.8 story-005, e.g. bard_inspire) resolves via the dedicated
        # ability-condition path — deduct its cost and land the condition on the target participant —
        # NOT through _resolve_ability_packet (which casts a spell). Pre-gated in _prevalidate_ability_focus.
        cond_ability = condition_ability(declared_ability(decl.action))
        if cond_ability is not None:
            return await _resolve_ability_condition_packet(
                session,
                attacker,
                decl,
                cond_ability,
                state=state,
                conn=conn,
                player=player,
                queries=queries,
                progress=progress,
            )
        return await _resolve_ability_packet(
            session,
            attacker,
            decl,
            state=state,
            cast_resolver=cast_resolver,
            conn=conn,
            player=player,
            cast_outcome=cast_outcome if cast_outcome is not None else AbilityCastOutcome(),
            progress=progress,
            damage_deps={
                "mutations": mutations,
                "queries": queries,
                "resolver": resolver,
                "concentration_break_mod": concentration_break_mod,
                "sink": sink,
            },
        )

    if decl.type is DeclarationType.MANEUVER:
        return combat_maneuver.resolve_maneuver(state, attacker, decl)

    if decl.type is not DeclarationType.ATTACK:
        # Non-attack declarations don't resolve mechanically yet, but a narrated rider
        # (e.g. Quick Change on a social INTERACT) still surfaces for the DM to voice.
        summary = {
            "actor_id": packet.actor_id,
            "resolved": False,
            "declaration_type": str(decl.type),
            "reason": f"{decl.type} resolution not yet implemented",
        }
        return _attach_riders(summary, attacker, decl)

    target = state.get_participant(decl.target_id) if decl.target_id else None
    # `action` was resolved once above (the single _find_action for this packet).
    if target is None:
        return {"actor_id": packet.actor_id, "resolved": False, "reason": f"target '{decl.target_id}' not found"}
    if target_unavailable(target, action):
        return {"actor_id": packet.actor_id, "resolved": False, "reason": f"{target.name} already fell"}
    if action is None:
        return {"actor_id": packet.actor_id, "resolved": False, "reason": f"action '{decl.action}' not found"}

    # A hostile mark action resolves without a roll (encounter_actions).
    if not attacker.is_ally and action_kind(action) in combat_marks.MARK_KINDS:
        kind = action_kind(action)
        outcome = combat_marks.resolve_mark_action(state, attacker, target, kind, cancelled=mark_cancelled)
        return {
            "actor_id": packet.actor_id,
            "declaration_type": str(decl.type),
            "action": decl.action,
            "target": target.name,
            **outcome,
        }

    return await combat_fate.attack_sequence(
        session,
        state,
        packet,
        attacker,
        target,
        action,
        attack_cursor=attack_cursor,
        progress=progress,
        mutations=mutations,
        queries=queries,
        resolver=resolver,
        concentration_break_mod=concentration_break_mod,
        conn=conn,
        sink=sink,
        reaction_ac_bonus=reaction_ac_bonus,
        reaction_save_advantage=reaction_save_advantage,
        shield_reaction=shield_reaction,
        grapple_blocked=grapple_blocked,
        publish_roll=publish_roll,
        movement=movement,
        movement_budget=movement_budget,
    )
