"""Ally attack substeps and the combat cursor used to resume them."""

from dataclasses import asdict

from livekit.agents.llm import ToolError

import check_resolution_attack
import combat_enhancers
import combat_resolution
import concealment
import conditions
import zhael_fate
from combat_ability import _attach_riders
from combat_attack_roll import attack_roll_inputs, promote_attack
from combat_down import damage_target_unavailable
from combat_fate_rolls import PacketRolls
from combat_item_rider import resolve_rider
from combat_support import _resolve_attack_packet, apply_rolled_attack


async def attack_sequence(
    session,
    state,
    packet,
    attacker,
    target,
    action,
    *,
    attack_cursor,
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
):
    decl = packet.declaration
    attack_summaries = attack_cursor.get("summaries", [])
    concealment_packet = attack_cursor.get("concealment")
    start = len(attack_summaries)
    for act in actions[start:]:
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
            attacker_data, target_ac, attack_mod = attack_roll_inputs(
                attacker, target, state.ac_modifiers.get(target.id, 0) + reaction_ac_bonus, state
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
                attack_cursor.update(
                    actions=actions,
                    target_id=target.id,
                    enemies_remaining=enemies_remaining,
                    is_first_attack=is_first_attack,
                    summaries=attack_summaries,
                    concealment=concealment_packet,
                    prepared=stored,
                    attacker_data=attacker_data,
                )
                return {"actor_id": attacker.id, "resolved": False, "reason": "awaiting a Zhael roll choice"}
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
                attack_cursor, actions, target, enemies_remaining, is_first_attack, attack_summaries, concealment_packet
            )
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
                    target,
                    enemies_remaining,
                    is_first_attack,
                    attack_summaries,
                    concealment_packet,
                )
                return {}
        if progress is not None:
            progress.steps.pop("swing", None)
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
        if damage_target_unavailable(target):
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
    if concealment_packet is not None:
        summary["concealment"] = concealment_packet
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
