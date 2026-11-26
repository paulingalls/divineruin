"""Per-packet/phase resolution helpers for the combat phase loop (split from
combat_turn.py to keep that file under the 500-line ceiling).

resolve_phase (in combat_turn) orchestrates the per-phase transaction; the
helpers here do the actual resolution work it drives: _prevalidate_ability_focus
gates player ability Focus before the loop, _resolve_one_packet dispatches a
single initiative-ordered packet to the right resolver (attack / ability /
de-escalate / defend), handing encounter-specific action kinds to combat_packet_special.
The helpers mutate in-memory
state and write through injected mutation/query modules, but own no transaction."""

from typing import Any

import abilities
import combat_cunning_action
import combat_maneuver
import combat_marks
import combat_martial
import combat_melee_approach
import combat_packet_special
import combat_packet_weapon
import combat_player_ability
import combat_recharge
import combat_retreat
import combat_spatial_declarations
import combat_turn_flight
import combat_voice_rules
import item_heal
import spell_casting
import thyra_thornwall
from combat_ability import _attach_riders, _find_action
from combat_ability_gate import MULTI_TARGET_WEAPON_ABILITIES, SINGLE_TARGET_WEAPON_ABILITIES, WAR_CRIES
from combat_action_availability import begin_execution, replay_valid
from combat_down import target_unavailable
from combat_enemy_action import resolve_enemy_strike
from combat_packet_gate import _prevalidate_ability_focus as _prevalidate_ability_focus
from combat_structures import action_has_direct_line, blocked_reason, line_blocker
from concealment import reveal_attacker
from condition_restrictions import cannot_act
from condition_sources import DeliveryRefused
from declarations import DeclarationType
from encounter_actions import action_kind
from session_data import SessionData


async def _resolve_one_packet(session, state, packet, *, _reshape_prepared=False, **deps) -> dict:
    from combat_veilrender import turn_start

    progress = deps.get("progress")
    player_movement = deps.get("player_movement")
    steps = progress.steps if progress is not None else player_movement.steps if player_movement is not None else {}
    held_head = deps.get("_held_head") or {}
    resuming_movement = player_movement is not None and player_movement.route is not None
    # Turn-start effects run once per round; a Zhael-held packet keeps them for its resumed summary.
    effects = steps.pop("turn_start_effects", None)
    if not (effects or resuming_movement or "legendary_kind" in held_head or held_head.get("opportunity_attack")):
        effects = await turn_start(
            session,
            state,
            state.get_participant(packet.actor_id),
            **{**deps, "progress": progress.scope("veilrender") if progress is not None else None},
        )
        if effects is None:
            return {}
    if packet.declaration.reshape and not _reshape_prepared:
        from combat_reshape_packet import ReshapeRefused, resolve_reshape

        try:
            if not await resolve_reshape(
                session, state, packet.actor_id, packet.declaration, steps, progress=progress, packet_deps=deps
            ):
                return {}
        except ReshapeRefused as error:
            return {"actor_id": packet.actor_id, "resolved": False, "reason": str(error)}
    result = await _resolve_action_packet(session, state, packet, turn_effects=effects, **deps)
    if "reshape_receipts" in steps:
        result["reshape"] = steps["reshape_receipts"]
    if (progress is not None and progress.paused) or (
        player_movement is not None and player_movement.route is not None
    ):
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
    player_movement=None,
    turn_effects: list[dict],
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

    forced_move = None
    held_head = _held_head or {}
    opportunity_attack = held_head.get("opportunity_attack", False)
    resuming_movement = player_movement is not None and player_movement.route is not None
    if not (resuming_movement or opportunity_attack or "legendary_kind" in held_head):
        from combat_turn_start import start_choir_packet

        forced_move = await start_choir_packet(
            session,
            state,
            attacker,
            conn=conn,
            concentration_break_mod=concentration_break_mod,
            sink=sink,
            progress=progress,
            effects=turn_effects,
        )
        if progress is not None and progress.paused:
            return {}
    if attacker is None or (attacker.is_fallen and not resuming_movement):
        return {"actor_id": packet.actor_id, "resolved": False, "reason": "actor unavailable"}
    if not resuming_movement and (blocked := cannot_act(attacker.conditions)):
        reason = f"{attacker.name} is {blocked[0]} and loses the phase"
        return {"actor_id": packet.actor_id, "resolved": False, "reason": reason}

    if combat_turn_flight.is_flight_turn(attacker, held_head):
        return await combat_turn_flight.flee(
            session,
            state,
            attacker,
            conn=conn,
            sink=sink,
            progress=progress.scope("turn_flight") if progress is not None else None,
        )

    retreating = attacker.is_ally and decl.type is DeclarationType.RETREAT
    if (combat_spatial_declarations.is_move(decl) or retreating) and forced_move is not None:
        return forced_move
    if combat_spatial_declarations.is_move(decl):
        if player_movement is not None:
            return await player_movement.move(attacker, decl) or {}
        return await thyra_thornwall.resolve_move(
            session, state, attacker, decl, conn=conn, sink=sink, progress=progress
        )

    if retreating:
        return await combat_retreat.resolve(
            session, state, attacker, decl, player_movement, conn=conn, sink=sink, progress=progress, queries=queries
        )

    if stale is not None:
        return {"actor_id": packet.actor_id, "resolved": False, "reason": stale}

    try:
        combat_voice_rules.guard_declaration(
            state, attacker, decl, war_cry_started=bool(progress and WAR_CRIES & progress.steps.keys())
        )
    except DeliveryRefused as e:
        return {"actor_id": attacker.id, "resolved": False, "reason": str(e)}

    if item_heal.is_consume(decl):
        return await item_heal.resolve_combat(session, state, attacker, decl, conn=conn, sink=sink, queries=queries)

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

    martial = combat_martial.attack_ability(decl)
    single_target = martial in SINGLE_TARGET_WEAPON_ABILITIES
    multi_target = martial in MULTI_TARGET_WEAPON_ABILITIES
    if martial is not None and single_target:
        name = abilities.get_ability(martial).name
        if player is None:
            raise ValueError(f"{name} requires a prevalidated player.")
        action = combat_martial.main_hand(player, name)

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
        if (
            not replay
            and action_has_direct_line(action)
            and not combat_melee_approach.is_melee(action)
            and (wall := line_blocker(state, attacker.id, decl.target_id))
        ):
            return {"actor_id": attacker.id, "resolved": False, "reason": blocked_reason(wall)}
        special = await combat_packet_special.resolve(
            session,
            state,
            attacker,
            action,
            decl,
            replay=replay,
            head=_held_head,
            progress=progress,
            conn=conn,
            mutations=mutations,
            queries=queries,
            concentration_break_mod=concentration_break_mod,
            sink=sink,
            reaction_save_advantage=reaction_save_advantage,
        )
        if special is not None:
            return special
        target = state.get_participant(decl.target_id) if decl.target_id else None
        if target is not None and not target_unavailable(target, action):
            movement_budget = combat_cunning_action.movement_allowance(state, attacker, decl)
            # Move before any roll is prepared, and only once: a held head carries its approach, and a
            # Zhael-held ally swing resumes through its attack cursor, never back through here.
            if _melee_approach is not None:
                movement = _melee_approach
            elif player_movement is not None:
                movement = await player_movement.approach(attacker, target, action, movement_budget)
                if movement is None:
                    return {}
            else:
                movement = await combat_melee_approach.prepare_packet(
                    session, state, attacker, target, action, movement_budget, progress
                )
                if movement is None:
                    return {}
            if movement.get("attack_resolved") is False:
                if decl.rider in ("dash", "disengage") and movement.get("movement_spent_ft", 0) > 0:
                    await combat_cunning_action.pay(attacker, queries=queries, conn=conn)
                return await thyra_thornwall.apply_contact(
                    session, state, attacker, movement, conn=conn, sink=sink, progress=progress
                )
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
                or single_target
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

    if decl.type is DeclarationType.ABILITY and not (single_target or multi_target):
        return await combat_player_ability.resolve(
            session,
            state,
            attacker,
            decl,
            conn=conn,
            player=player,
            sink=sink,
            progress=progress,
            queries=queries,
            cast_resolver=cast_resolver,
            cast_outcome=cast_outcome,
            mutations=mutations,
            resolver=resolver,
            concentration_break_mod=concentration_break_mod,
            player_movement=player_movement,
        )

    if decl.type is DeclarationType.MANEUVER:
        if wall := line_blocker(state, attacker.id, decl.target_id, melee=True):
            return {"actor_id": attacker.id, "resolved": False, "reason": blocked_reason(wall)}
        return combat_maneuver.resolve_maneuver(state, attacker, decl)

    if decl.type is not DeclarationType.ATTACK and not (single_target or multi_target):
        summary = {
            "actor_id": packet.actor_id,
            "resolved": False,
            "declaration_type": str(decl.type),
            "reason": f"{decl.type} resolution not yet implemented",
        }
        return _attach_riders(summary, attacker, decl)

    attack_deps: dict[str, Any] = dict(
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
    if multi_target:
        if player is None:
            raise ValueError("A multi-target weapon ability requires a prevalidated player.")
        return await combat_packet_weapon.resolve_multi_target(session, state, packet, attacker, player, attack_deps)

    target = state.get_participant(decl.target_id) if decl.target_id else None
    # `action` was resolved once above (the single _find_action for this packet).
    if target is None or target_unavailable(target, action):
        reason = f"target '{decl.target_id}' not found" if target is None else f"{target.name} already fell"
        summary: dict = {"actor_id": packet.actor_id, "resolved": False, "reason": reason}
        if (
            attacker.type == "player"
            and action is not None
            and (decl.type is DeclarationType.ATTACK or single_target)
            and (reveal := await reveal_attacker(attacker.id, conn=conn, queries=queries))
        ):
            summary["concealment"] = reveal
        return summary
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

    return await combat_packet_weapon.resolve(
        session,
        state,
        packet,
        attacker,
        target,
        action,
        _held_head,
        attack_deps,
        opportunity_attack=opportunity_attack,
        player_movement=player_movement,
    )
