"""Per-packet/phase resolution helpers for the combat phase loop (split from
combat_turn.py to keep that file under the 500-line ceiling).

resolve_phase (in combat_turn) orchestrates the per-phase transaction; the
helpers here do the actual resolution work it drives: _prevalidate_ability_focus
gates player ability Focus before the loop, _resolve_one_packet dispatches a
single initiative-ordered packet to the right resolver (attack / ability /
de-escalate / defend), and _resolve_tick_saves resolves the Beat-4 save-to-clear
conditions the wrap surfaces. All are pure-ish helpers — they mutate in-memory
state and write through injected mutation/query modules, but own no transaction."""

import combat_enhancers
import combat_maneuver
import combat_marks
import combat_recharge
import combat_resolution
import combat_spatial_declarations
import combat_voice_rules
import conditions
import spell_casting
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
from combat_enemy_action import resolve_enemy_strike
from combat_enemy_active import resolve_active
from combat_packet_gate import _prevalidate_ability_focus as _prevalidate_ability_focus
from combat_support import _resolve_attack_packet
from condition_restrictions import cannot_act
from condition_sources import DeliveryRefused
from declarations import DeclarationType
from encounter_actions import action_kind
from session_data import SessionData

# Beat-4 save-to-clear DC (M4.3, story-004): the spec's end-of-turn condition saves (Frightened's
# WIS save) have no per-condition DC, so use a fixed moderate DC. A seam: a future per-condition DC
# would replace this constant (assumption f760751a1109).
_CONDITION_CLEAR_DC = 10


def _resolve_tick_saves(state, tick_conditions_due, save_resolver):
    """Resolve the Beat-4 save-to-clear conditions the wrap surfaced (M4.3, story-004).

    For each {actor_id, type, save, source}, roll the actor's save against the clear DC; on a SUCCESS
    remove that condition from the actor (it clears), on a failure it persists. Pure in-memory: the
    removal rides the phase's existing save_combat_state / end-combat write — no extra persist here,
    no client event (narration-only). The engine never rolls; this is where the roll happens.
    """
    for event in tick_conditions_due:
        actor = state.get_participant(event["actor_id"])
        if actor is None:
            continue
        # Shared participant-save SSOT (roll_participant_save): builds player_data from the actor and
        # expands the 3-letter tick_save ("wis" -> "wisdom"). Engine-auto tick-clear: never spends the
        # actor's +1d4 (bonus_dice_eligible=False, M4.8 story-003), and include_proficiency=False keeps
        # the pre-M13 clear odds — folding proficiency in here would be an untested M4.3 balance shift.
        result = save_resolver.roll_participant_save(
            actor,
            event["save"],
            _CONDITION_CLEAR_DC,
            event["type"],
            bonus_dice_eligible=False,
            include_proficiency=False,
        )
        if result.success:
            actor.conditions = conditions.remove_condition(actor.conditions, event["type"])


async def _resolve_one_packet(
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

    stale = choir_encounter.stale_reason(state, packet.actor_id, decl)
    if stale is None:
        choir_encounter.guard_declaration(state, packet.actor_id, decl)

    aura = await choir_encounter.turn_start(
        session, state, attacker, conn=conn, concentration_break_mod=concentration_break_mod
    )
    if aura is not None and sink is not None:
        import event_types as E
        from combat_events import emit_or_publish

        await emit_or_publish(
            sink, session.room, E.DICE_ROLL, {"roll_type": "choir_aura", **aura}, event_bus=session.event_bus
        )

    from choir_effects import approach

    forced_move = approach(state, attacker)
    if combat_spatial_declarations.is_move(decl) and forced_move is not None:
        return forced_move
    if combat_spatial_declarations.is_move(decl):
        return combat_spatial_declarations.apply_move(state, attacker, decl)

    if attacker is None or attacker.is_fallen:
        return {"actor_id": packet.actor_id, "resolved": False, "reason": "actor unavailable"}
    if blocked := cannot_act(attacker.conditions):
        reason = f"{attacker.name} is {blocked[0]} and loses the phase"
        return {"actor_id": packet.actor_id, "resolved": False, "reason": reason}

    if stale is not None:
        return {"actor_id": packet.actor_id, "resolved": False, "reason": stale}

    try:
        combat_voice_rules.guard_declaration(state, attacker, decl)
    except DeliveryRefused as e:
        return {"actor_id": attacker.id, "resolved": False, "reason": str(e)}

    if decl.type is DeclarationType.INTERACT and decl.action in choir_encounter.SEARCH_ACTIONS:
        return await choir_encounter.search(session, state, attacker, decl, queries=queries, conn=conn)

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

    if action is not None:
        replay = _held_head is not None and replay_valid(state, _held_head, attacker, action, decl)
        pending_execution = any(
            head.get("actor_id") == attacker.id and head.get("execution_receipt") is not None
            for head in state.held_actions
        )
        if (
            (_held_head is not None and not replay)
            or (_held_head is None and pending_execution)
            or (not replay and not combat_recharge.available(attacker, action))
        ):
            return {"actor_id": attacker.id, "resolved": False, "reason": "action unavailable"}
        if not attacker.is_ally and action_kind(action) in ("healing", "prepare_attack"):
            action = begin_execution(state, attacker, action, decl)
            return resolve_active(state, attacker, action, decl)
        if action_kind(action) in ("charm", "silence"):
            from choir_actions import resolve_effect

            return await resolve_effect(
                session, state, attacker, action, decl, reaction_save_advantage=reaction_save_advantage
            )
        target = state.get_participant(decl.target_id) if decl.target_id else None
        if replay:
            assert _held_head is not None
            action = _held_head["executed_action"]
        elif (
            target is not None
            and not target.is_fallen
            and not (action.get("resolution") == "save" and action.get("type") == "area")
            and (
                decl.type is DeclarationType.ATTACK
                or action.get("applies_condition")
                or action.get("half_on_success") is True
            )
        ):
            action = begin_execution(state, attacker, action, decl)

    if (
        not attacker.is_ally
        and action is not None
        and action.get("resolution") == "save"
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
            publish_roll=publish_roll,
        )
        if enemy_summary is not None:
            return enemy_summary

    if decl.type is DeclarationType.ABILITY:
        # (Enemy condition-infliction ABILITY is handled by the type-agnostic branch above, which
        # routes both ATTACK and ABILITY enemy actions carrying applies_condition. The branches
        # below are the player-oriented paths.)
        # De-escalate (M4.6a story-004) is an ABILITY but resolves socially, not as a cast:
        # contested gate + one argument that can end combat. Its Focus/lockout were pre-gated
        # in _prevalidate_ability_focus, and ``player`` is the for_update row from there.
        if (decl.action or "").lower() == "de_escalate":
            return await _resolve_deescalation_packet(
                session, attacker, decl, state=state, conn=conn, player=player, sink=sink
            )
        # A non-spell condition ability (M4.8 story-005, e.g. bard_inspire) resolves via the dedicated
        # ability-condition path — deduct its cost and land the condition on the target participant —
        # NOT through _resolve_ability_packet (which casts a spell). Pre-gated in _prevalidate_ability_focus.
        cond_ability = condition_ability(declared_ability(decl.action))
        if cond_ability is not None:
            return await _resolve_ability_condition_packet(
                session, attacker, decl, cond_ability, state=state, conn=conn, player=player
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
    if target.is_fallen:
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

    # Enhancers EXPAND a single declaration: extra_attack/shield_bash turn one ATTACK into a
    # short attack sequence (still ONE declaration, never a second), narrated riders attach
    # below. attack_sequence is [action] when the actor has no mechanical enhancer (AC3: no
    # phantom expansion → the summary stays the flat single-attack shape).
    actions = combat_enhancers.attack_sequence(attacker.enhancers, action)
    # Encounter-context dramatic signals (M4.5, story-004) the per-attack resolver can't see:
    # the count of foes still standing as this declaration is resolved (==1 => last enemy), and
    # whether any attack has resolved this whole combat yet (the opening strike). Computed once
    # before the swing loop so all swings of an expanded sequence share one verdict.
    enemies_remaining = sum(1 for p in state.participants if p.type == "enemy" and not p.is_fallen)
    is_first_attack = not state.first_attack_resolved
    attack_summaries: list[dict] = []
    for act in actions:
        sub = await _resolve_attack_packet(
            session,
            attacker,
            act,
            target,
            # state.ac_modifiers is Defend's phase-scoped +2, per participant; reaction_ac_bonus is
            # a pre-roll reaction's +2 against THIS held blow only (story-018), which is why it
            # rides the call instead of being written into that map.
            target_ac_bonus=state.ac_modifiers.get(target.id, 0) + reaction_ac_bonus,
            shield_reaction=shield_reaction,
            grapple_blocked=grapple_blocked,
            enemies_remaining=enemies_remaining,
            is_first_attack_of_combat=is_first_attack,
            mutations=mutations,
            queries=queries,
            resolver=resolver,
            concentration_break_mod=concentration_break_mod,
            combat_state=state,
            conn=conn,
            sink=sink,
            publish_roll=publish_roll,
        )
        attack_summaries.append(sub)
        # Remove attack-spent conditions before the next swing in an expanded declaration. The
        # first consuming swing leaves later consumed_conditions empty. Persistence rides the
        # phase's save_combat_state.
        if sub.get("consumed_conditions"):
            attacker.conditions = conditions.remove_conditions(attacker.conditions, sub["consumed_conditions"])
        # Preserve request_attack's old behavior: any player swing — hit OR miss — arms the
        # per-encounter weapon-durability accrual that end_combat applies. Only the extra
        # crit-vs-heavy-armor cost (2 hits) is gated on a critical hit landing. M18 story-003:
        # arm the SWINGING member's own flags (attacker.id == that player's id, combat_init), so a
        # non-primary member's swings accrue THEIR weapon's durability, not the primary's.
        if attacker.type == "player":
            # Non-raising member() + skip, matching combat_end's accrual loop: a player participant
            # is a party member in prod (combat_init), but a stray one must not abort a resolved
            # phase over a durability scratch flag. The two ends of this feature agreed on the
            # fail-safe everywhere except here, where member_state raised inside the phase tx.
            member = session.party.member(attacker.id)
            if member is not None:
                member.weapon_used = True
                if sub["hit"] and sub["critical"] and combat_resolution.is_heavily_armored(target.ac):
                    member.weapon_crit_vs_heavy = True
        # An expanded sequence stops once the target drops — no swinging at a fallen foe.
        if target.is_fallen:
            break

    # The first attack of the combat has now resolved; flips the combat-scoped flag so a
    # later attack no longer earns the dramatic "first_attack" promotion (story-004).
    state.first_attack_resolved = True

    summary = dict(attack_summaries[0])
    if len(attack_summaries) > 1:
        # Report the expansion: per-attack detail under "attacks", flat keys aggregated.
        # Damage/hit/critical/concentration accumulate across swings; the target-state keys
        # (hp_status, fallen) must reflect the FINAL swing — the kill on the second hit, not
        # the goblin-still-up snapshot from the first — or the DM narrates a fallen foe alive.
        last = attack_summaries[-1]
        summary["attacks"] = attack_summaries
        summary["damage"] = sum(s["damage"] for s in attack_summaries)
        summary["hit"] = any(s["hit"] for s in attack_summaries)
        summary["critical"] = any(s["critical"] for s in attack_summaries)
        summary["target_hp_status"] = last["target_hp_status"]
        summary["target_fallen"] = last["target_fallen"]
        summary["concentration_broken"] = next(
            (s["concentration_broken"] for s in attack_summaries if s["concentration_broken"]), None
        )
        # Any swing being dramatic makes the declaration dramatic. Each swing rolls its
        # own d20 and runs its own killing-blow check, so a later swing can be dramatic
        # while the first is routine — take the FIRST dramatic swing's context so the
        # aggregated dramatic flag and its reason label never disagree (story-004).
        summary["dramatic"] = any(s["dramatic"] for s in attack_summaries)
        summary["context"] = next((s["context"] for s in attack_summaries if s["dramatic"]), "")
    summary["actor_id"] = packet.actor_id
    summary["resolved"] = True
    return _attach_riders(summary, attacker, decl)
