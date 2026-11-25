"""Ally attack substeps and the combat cursor used to resume them."""

from dataclasses import asdict

import architect_reaction
import check_resolution_attack
import combat_attack_summary
import combat_cunning_action
import combat_enhancers
import combat_martial
import combat_melee_approach
import combat_resolution
import concealment
import conditions
import zhael_fate
from combat_ability import _attach_riders, _with_variant
from combat_ability_gate import (
    DEVASTATING_STRIKE,
    ELECTIVE_ATTACK_RIDERS,
    RECKLESS_ASSAULT_RIDER,
    SHIELD_BASH,
    declared_ability,
)
from combat_attack_roll import attack_roll_inputs, promote_attack, spend_sneak_attack
from combat_down import damage_target_unavailable
from combat_item_rider import resolve_rider
from combat_support import _resolve_attack_packet, apply_rolled_attack
from patron_synergy_combat import attack_player, veiled_strike


async def attack_sequence(
    session,
    state,
    packet,
    attacker,
    target,
    action,
    *,
    attack_cursor,
    movement=None,
    movement_budget=None,
    **deps,
):
    # Enhancers EXPAND a single declaration: extra_attack/shield_bash turn one ATTACK into a
    # short attack sequence (still ONE declaration, never a second), narrated riders attach
    # below. attack_sequence is [action] when the actor has no mechanical enhancer (AC3: no
    # phantom expansion → the summary stays the flat single-attack shape).
    martial = combat_martial.attack_ability(packet.declaration)
    enhancers = attacker.enhancers
    if martial == SHIELD_BASH:
        enhancers = [enhancer for enhancer in enhancers if enhancer != combat_enhancers.SHIELD_BASH]
    actions = combat_enhancers.attack_sequence(enhancers, action)
    if attack_cursor is None:
        attack_cursor = {}
    if martial == DEVASTATING_STRIKE or martial in ELECTIVE_ATTACK_RIDERS.values():
        resolved = declared_ability(martial)
        assert resolved is not None
        variant = await combat_martial.pay(attacker.id, resolved, queries=deps["queries"], conn=deps["conn"])
        if martial in ELECTIVE_ATTACK_RIDERS.values():
            actions = [{**swing, "advantage": True} for swing in actions]
            attack_cursor["variant_receipt"] = _with_variant({}, variant)
            if packet.declaration.rider == RECKLESS_ASSAULT_RIDER:
                attacker.conditions = conditions.apply_condition(
                    attacker.conditions, RECKLESS_ASSAULT_RIDER, source=martial
                )
    # Encounter-context dramatic signals (M4.5, story-004) the per-attack resolver can't see:
    # the count of foes still standing as this declaration is resolved (==1 => last enemy), and
    # whether any attack has resolved this whole combat yet (the opening strike). Computed once
    # before the swing loop so all swings of an expanded sequence share one verdict.
    enemies_remaining = sum(1 for p in state.participants if p.type == "enemy" and not p.is_fallen)
    is_first_attack = not state.first_attack_resolved
    return await continue_attack(
        session,
        state,
        packet,
        attacker,
        target,
        actions,
        enemies_remaining,
        is_first_attack,
        attack_cursor=attack_cursor,
        movement=movement,
        movement_budget=movement_budget,
        **deps,
    )


async def continue_attack(
    session,
    state,
    packet,
    attacker,
    target,
    actions,
    enemies_remaining,
    is_first_attack,
    *,
    attack_cursor,
    mutations,
    queries,
    resolver,
    concentration_break_mod,
    conn,
    sink,
    reaction_ac_bonus=0,
    reaction_save_advantage=False,
    shield_reaction=None,
    grapple_blocked=False,
    publish_roll=True,
    progress=None,
    movement=None,
    movement_budget=None,
    player_movement=None,
):
    decl = packet.declaration
    attack_summaries = attack_cursor.get("summaries", [])
    concealment_packet = attack_cursor.get("concealment")
    # The declaration's melee approach (made before any roll) and its shared movement allowance;
    # a resumed cursor carries both so a held swing never moves the attacker twice.
    movement = attack_cursor.get("movement", movement or {})
    movement_budget = attack_cursor.get("movement_budget", movement_budget if movement_budget is not None else {})
    declared_target = target
    martial = combat_martial.attack_ability(decl)

    def checkpoint() -> None:
        attack_cursor.update(
            actions=actions,
            target_id=declared_target.id,
            enemies_remaining=enemies_remaining,
            is_first_attack=is_first_attack,
            summaries=attack_summaries,
            concealment=concealment_packet,
            movement=movement,
            movement_budget=movement_budget,
        )

    start = len(attack_summaries)
    interrupted = None
    for index, act in enumerate(actions[start:], start):
        if index == 0 or act == actions[0]:
            swing_move = movement
        elif "swing_move" in attack_cursor:
            swing_move = attack_cursor["swing_move"]
        elif player_movement is not None:
            swing_move = await player_movement.approach(attacker, declared_target, act, movement_budget)
            if swing_move is None:
                checkpoint()
                return {}
            attack_cursor["swing_move"] = swing_move
        else:
            swing_move = combat_melee_approach.prepare(state, attacker, declared_target, act, movement_budget)
        if index > 0 and act == actions[0] and swing_move:
            swing_move = {**swing_move, "moved_ft": 0, "closed_distance": False}
        if swing_move.get("attack_resolved") is False:
            attack_summaries.append(swing_move)
            if not swing_move["resolved"]:
                interrupted = swing_move
            break
        if martial == DEVASTATING_STRIKE and not any(sub.get("hit") for sub in attack_summaries):
            count = 3 if attacker.level >= 17 else 2 if attacker.level >= 10 else 1
            act = {**act, "devastating_strike_dice": count}
        target, interception = architect_reaction.weapon_target(
            state, attacker, declared_target, act, attack_cursor, index
        )
        if interception.get("resolved") is False:
            attack_summaries.append({**swing_move, **interception})
            break
        swing = progress.scope("swing") if progress is not None else None
        prepared_data = attack_cursor.get("prepared")
        resumed_swing = swing is not None and ("damage_receipt" in swing.steps or "attack_summary" in swing.steps)
        reveal = start == 0 and not attack_summaries and attacker.type == "player" and not resumed_swing
        strike_mode = None
        player = None
        if reveal and prepared_data is None:
            player = await attack_player(attacker, queries=queries, conn=conn)
            assert player is not None
            if concealment.gift_lifetime(player):
                strike_mode = veiled_strike(player)
        prepared = None
        if prepared_data is not None:
            prepared = check_resolution_attack.PreparedAttack.from_dict(prepared_data)
            attacker_data = attack_cursor["attacker_data"]
        elif (
            swing is not None
            and "damage_receipt" not in swing.steps
            and "attack_summary" not in swing.steps
            and attacker.is_ally
            and (candidates := await zhael_fate.candidates(session, queries=queries, conn=conn)).choices(attacker.id)
        ):
            if player is None:
                player = await attack_player(attacker, queries=queries, conn=conn)
            defender = await attack_player(target, queries=queries, conn=conn)
            attacker_data, target_ac, attack_mod = attack_roll_inputs(
                attacker,
                target,
                state.ac_modifiers.get(target.id, 0) + reaction_ac_bonus,
                state,
                act,
                player=player,
                defender=defender,
                veiled_strike=strike_mode,
            )
            prepared = check_resolution_attack.prepare_attack(
                attacker_data, act, target_ac, attack_mod=attack_mod, target_conditions=target.conditions
            )
            if await swing.phase.hold(
                session,
                "attack",
                attacker.id,
                prepared.original,
                prepared.d20,
                queries=queries,
                conn=conn,
                candidates=candidates,
            ):
                stored = asdict(prepared)
                stored["consumed"] = list(prepared.consumed)
                checkpoint()
                attack_cursor.update(
                    prepared=stored,
                    attacker_data=attacker_data,
                )
                return {
                    "actor_id": attacker.id,
                    "resolved": False,
                    "reason": "awaiting a Zhael roll choice",
                    **interception,
                }
        if reveal:
            concealment_packet = await concealment.reveal_attacker(attacker.id, conn=conn, queries=queries)
        bash = martial == SHIELD_BASH and index == len(actions) - 1
        if bash and not resumed_swing:
            resolved = declared_ability(SHIELD_BASH)
            assert resolved is not None
            await combat_martial.pay(attacker.id, resolved, queries=queries, conn=conn)
        stored_summary = swing.steps.get("attack_summary") if swing is not None else None
        if stored_summary is not None:
            sub = stored_summary
        elif prepared is None:
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
                progress=swing,
                veiled_strike=strike_mode,
            )
        else:
            result = check_resolution_attack.finish_attack(
                attacker_data,
                act,
                prepared.d20.dc,
                target.hp_current,
                prepared,
                swing.phase.select(prepared.original) if swing is not None else prepared.original,
                damage_mult=attacker.damage_mult,
                target_conditions=target.conditions,
            )
            spend_sneak_attack(attacker, state, result)
            result = promote_attack(result, enemies_remaining, is_first_attack)
            sub = await apply_rolled_attack(
                session,
                attacker,
                act,
                target,
                result,
                prepared.d20.dc,
                shield_reaction=shield_reaction,
                grapple_blocked=grapple_blocked,
                mutations=mutations,
                queries=queries,
                concentration_break_mod=concentration_break_mod,
                combat_state=state,
                conn=conn,
                sink=sink,
                publish_roll=publish_roll,
                progress=swing,
            )
            if prepared_data is not None:
                del attack_cursor["prepared"], attack_cursor["attacker_data"]

        if swing is not None and swing.paused:
            checkpoint()
            return {}
        if bash or "durability_rider" in act:
            rider_progress = swing.scope("rider") if swing is not None else None
            if bash:
                await combat_martial.bash_save(session, state, attacker, target, sub, progress=rider_progress)
            if "durability_rider" in act and not (swing is not None and swing.paused):
                await resolve_rider(
                    session,
                    attacker,
                    target,
                    act,
                    decl,
                    sub,
                    queries=queries,
                    conn=conn,
                    sink=sink,
                    reaction_save_advantage=reaction_save_advantage,
                    progress=swing.scope("rider") if swing is not None else None,
                )
            if swing is not None and swing.paused:
                swing.steps["attack_summary"] = sub
                checkpoint()
                return {}
        if progress is not None:
            progress.steps.pop("swing", None)
        if interception:
            sub.update(interception, target_id=target.id)
            attack_cursor.pop("reactive_architecture")
        if martial == combat_cunning_action.CUNNING_ACTION and index == 0 and "hit" in sub:
            await combat_cunning_action.pay(attacker, queries=queries, conn=conn)
        sub.update(swing_move)
        attack_summaries.append(sub)
        attack_cursor.pop("swing_move", None)
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
        if damage_target_unavailable(declared_target):
            break

    # The first attack of the combat has now resolved; flips the combat-scoped flag so a
    # later attack no longer earns the dramatic "first_attack" promotion (story-004).
    state.first_attack_resolved = True

    summary = combat_attack_summary.aggregate(attack_summaries, moved=bool(movement))
    if concealment_packet is not None:
        summary["concealment"] = concealment_packet
    if interrupted is None and martial == combat_cunning_action.CUNNING_ACTION and "hit" in summary:
        summary["cunning_action"] = {"rider": decl.rider}
        if decl.rider == "hide":
            hidden = await combat_cunning_action.hide(
                session,
                state,
                attacker,
                queries=queries,
                conn=conn,
                progress=progress.scope("cunning_hide") if progress is not None else None,
            )
            if hidden is None:
                checkpoint()
                return {}
            summary["cunning_action"].update(hidden)
    if effects := attack_cursor.pop("turn_start_effects", None):
        summary["turn_start_effects"] = effects
    summary.update(attack_cursor.get("variant_receipt", {}))
    summary["actor_id"] = packet.actor_id
    summary["resolved"] = interrupted is None
    if interrupted is not None:
        summary.update(attack_resolved=False, reason=interrupted["reason"])
    return _attach_riders(summary, attacker, decl)
