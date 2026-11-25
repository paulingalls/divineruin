"""Resolve the ally band and persist its place while a declaration is suspended."""

from livekit.agents.llm import ToolError

from combat_fate import continue_attack
from combat_fate_rolls import PacketRolls
from combat_player_movement import PlayerMovement


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
        movement = PlayerMovement(session, state, steps, packet_deps, fate_rolls, summaries)
        if movement.route is not None and not await movement.advance():
            return summaries
        player_movement = movement if actor is not None and actor.type == "player" else None
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
                    player_movement=player_movement,
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
                    player_movement=player_movement,
                )
        if fate_rolls.pending is not None or state.open_window is not None:
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
