"""Ally attack substeps and the combat cursor used to resume them."""

from dataclasses import asdict

from livekit.agents.llm import ToolError

import architect_reaction
import check_resolution_attack
import combat_attack_summary
import combat_enhancers
import combat_melee_approach
import combat_resolution
import concealment
import conditions
import zhael_fate
from combat_ability import _attach_riders
from combat_attack_roll import attack_roll_inputs, promote_attack, spend_sneak_attack
from combat_down import damage_target_unavailable
from combat_fate_rolls import PacketRolls
from combat_item_rider import resolve_rider
from combat_support import _resolve_attack_packet, apply_rolled_attack
from patron_synergy_combat import attack_player


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
    actions = combat_enhancers.attack_sequence(attacker.enhancers, action)
    # Encounter-context dramatic signals (M4.5, story-004) the per-attack resolver can't see:
    # the count of foes still standing as this declaration is resolved (==1 => last enemy), and
    # whether any attack has resolved this whole combat yet (the opening strike). Computed once
    # before the swing loop so all swings of an expanded sequence share one verdict.
    enemies_remaining = sum(1 for p in state.participants if p.type == "enemy" and not p.is_fallen)
    is_first_attack = not state.first_attack_resolved
    if attack_cursor is None:
        attack_cursor = {}
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
):
    decl = packet.declaration
    attack_summaries = attack_cursor.get("summaries", [])
    concealment_packet = attack_cursor.get("concealment")
    # The declaration's melee approach (made before any roll) and its shared movement allowance;
    # a resumed cursor carries both so a held swing never moves the attacker twice.
    movement = attack_cursor.get("movement", movement or {})
    movement_budget = attack_cursor.get("movement_budget", movement_budget if movement_budget is not None else {})
    declared_target = target
    start = len(attack_summaries)
    for index, act in enumerate(actions[start:], start):
        swing_move = (
            movement
            if index == 0 or act == actions[0]
            else combat_melee_approach.prepare(state, attacker, declared_target, act, movement_budget)
        )
        if index > 0 and act == actions[0] and swing_move:
            swing_move = {**swing_move, "moved_ft": 0, "closed_distance": False}
        if swing_move.get("attack_resolved") is False:
            attack_summaries.append(swing_move)
            break
        target, interception = architect_reaction.weapon_target(
            state, attacker, declared_target, act, attack_cursor, index
        )
        if interception.get("resolved") is False:
            attack_summaries.append({**swing_move, **interception})
            break
        swing = progress.scope("swing") if progress is not None else None
        prepared_data = attack_cursor.get("prepared")
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
                store_swing(
                    attack_cursor,
                    actions,
                    declared_target,
                    enemies_remaining,
                    is_first_attack,
                    attack_summaries,
                    concealment_packet,
                )
                attack_cursor.update(
                    prepared=stored,
                    attacker_data=attacker_data,
                    movement=movement,
                    movement_budget=movement_budget,
                )
                return {
                    "actor_id": attacker.id,
                    "resolved": False,
                    "reason": "awaiting a Zhael roll choice",
                    **interception,
                }
        resumed_swing = swing is not None and ("damage_receipt" in swing.steps or "attack_summary" in swing.steps)
        if start == 0 and not attack_summaries and attacker.type == "player" and not resumed_swing:
            concealment_packet = await concealment.reveal_attacker(attacker.id, conn=conn, queries=queries)
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
            store_swing(
                attack_cursor,
                actions,
                declared_target,
                enemies_remaining,
                is_first_attack,
                attack_summaries,
                concealment_packet,
            )
            attack_cursor.update(movement=movement, movement_budget=movement_budget)
            return {}
        if "durability_rider" in act:
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
                store_swing(
                    attack_cursor,
                    actions,
                    declared_target,
                    enemies_remaining,
                    is_first_attack,
                    attack_summaries,
                    concealment_packet,
                )
                attack_cursor.update(movement=movement, movement_budget=movement_budget)
                return {}
        if progress is not None:
            progress.steps.pop("swing", None)
        if interception:
            sub.update(interception, target_id=target.id)
            attack_cursor.pop("reactive_architecture")
        sub.update(swing_move)
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
        if damage_target_unavailable(declared_target):
            break

    # The first attack of the combat has now resolved; flips the combat-scoped flag so a
    # later attack no longer earns the dramatic "first_attack" promotion (story-004).
    state.first_attack_resolved = True

    summary = combat_attack_summary.aggregate(attack_summaries, moved=bool(movement))
    if concealment_packet is not None:
        summary["concealment"] = concealment_packet
    if effects := attack_cursor.pop("turn_start_effects", None):
        summary["turn_start_effects"] = effects
    summary["actor_id"] = packet.actor_id
    summary["resolved"] = True
    return _attach_riders(summary, attacker, decl)


def store_swing(cursor, actions, target, enemies_remaining, is_first_attack, summaries, concealment):
    cursor.update(
        actions=actions,
        target_id=target.id,
        enemies_remaining=enemies_remaining,
        is_first_attack=is_first_attack,
        summaries=summaries,
        concealment=concealment,
    )


def begin_ally_pass(state, allies, hostiles, players_by_id):
    from combat_turn_start import ally_turns

    return {
        "turns": [
            [actor.id if actor is not None else None, packet.actor_id if packet is not None else None]
            for actor, packet in ally_turns(state, allies)
        ],
        "hostiles": [packet.actor_id for packet in hostiles],
        "prevalidated": list(players_by_id),
        "deescalation_round": state.deescalation_scene.round_counter,
        "attack": {},
    }


def held_argument(cursor):
    return (cursor or {}).get("steps", {}).get("deescalation", {}).get("argument")


async def lock_remaining_players(cursor, queries, conn):
    remaining = {packet_id for _, packet_id in cursor["turns"]}
    players = {}
    for player_id in cursor["prevalidated"]:
        if player_id not in remaining:
            continue
        player = await queries.get_player(player_id, conn=conn, for_update=True)
        if player is None:
            raise ToolError(f"Unknown player: {player_id}")
        players[player_id] = player
    return players


async def run_ally_pass(session, state, cursor, players, *, fate_rolls, resolve_packet, packet_deps):
    from combat_deescalation import resume_deescalation
    from combat_hold import hold_enemy_packets
    from combat_phase import PhaseBeat, _resolve_packets
    from combat_turn_start import turn_start

    packets = {packet.actor_id: packet for packet in _resolve_packets(state)}
    summaries = []
    while cursor["turns"]:
        actor_id, packet_id = cursor["turns"][0]
        actor = state.get_participant(actor_id) if actor_id is not None else None
        attack = cursor["attack"]
        steps = cursor.setdefault("steps", {})
        progress = (
            PacketRolls(
                fate_rolls, steps, packet_deps["queries"], packet_deps["conn"], cursor.get("deescalation_round")
            )
            if session.fate_lock.locked() or steps or attack
            else None
        )
        if held_argument(cursor) is not None:
            assert progress is not None and packet_id is not None
            packet = packets.get(packet_id)
            summary = await resume_deescalation(
                session,
                state,
                packet_id,
                packet.declaration if packet is not None else None,
                players.get(packet_id),
                progress=progress.scope("deescalation"),
                sink=packet_deps["sink"],
            )
        elif attack:
            packet = packets[packet_id]
            attacker = state.get_participant(packet_id)
            target = state.get_participant(attack["target_id"])
            assert attacker is not None and target is not None
            if attacker.type == "player" and (
                attacker.id == session.departing_player_id or attacker.id not in session.present_member_ids
            ):
                fate_rolls.kept = None
                summary = {
                    "actor_id": attacker.id,
                    "resolved": False,
                    "outcome": "cancelled",
                    "reason": "The original roller is no longer present.",
                }
            else:
                summary = await continue_attack(
                    session,
                    state,
                    packet,
                    attacker,
                    target,
                    attack["actions"],
                    attack["enemies_remaining"],
                    attack["is_first_attack"],
                    attack_cursor=attack,
                    progress=progress,
                    **{
                        key: packet_deps[key]
                        for key in ("mutations", "queries", "resolver", "concentration_break_mod", "conn", "sink")
                    },
                )
        else:
            if actor is not None and not steps.get("turn_started"):
                started = await turn_start(
                    session,
                    state,
                    actor,
                    progress=progress.scope("turn_start") if progress is not None else None,
                    **packet_deps,
                )
                if fate_rolls.pending is not None:
                    state.beat = PhaseBeat.RESOLUTION
                    state.ally_continuation = cursor
                    return summaries
                steps["turn_started"] = True
                if started is not None:
                    summaries.append(started)
            if packet_id is None:
                cursor.pop("steps", None)
                cursor["turns"].pop(0)
                continue
            if actor is not None and not actor.is_ally:
                summary = {"actor_id": actor.id, "resolved": False, "reason": "actor became hostile"}
            else:
                summary = await resolve_packet(
                    session,
                    state,
                    packets[packet_id],
                    **packet_deps,
                    players_by_id=players,
                    attack_cursor=attack,
                    progress=progress,
                )
        if fate_rolls.pending is not None:
            if "reactive_architecture" in summary:
                summaries.append(summary)
            state.beat = PhaseBeat.RESOLUTION
            state.ally_continuation = cursor
            return summaries
        summaries.append(summary)
        cursor["attack"] = {}
        cursor.pop("steps", None)
        cursor["turns"].pop(0)

    state.held_actions = hold_enemy_packets(state, [packets[pid] for pid in cursor["hostiles"]])
    state.ally_continuation = None
    state.beat = PhaseBeat.NARRATION
    return summaries
