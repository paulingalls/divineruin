"""Resolve the ally band and persist its place while a declaration is suspended."""

from typing import TYPE_CHECKING

from livekit.agents.llm import ToolError

import combat_field_medic
import combat_spatial_declarations
from combat_fate import continue_attack
from combat_fate_rolls import PacketRolls
from combat_player_movement import PlayerMovement
from declarations import resolve_declaration

if TYPE_CHECKING:
    from combat_participant import CombatParticipant
    from combat_state import CombatState
    from session_data import SessionData


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


def cancel_queued_move(state: "CombatState", ally_id: str) -> bool:
    cursor = state.ally_continuation
    if cursor is None:
        return False
    for turn in cursor["turns"][1:]:
        if turn[1] != ally_id:
            continue
        declaration = resolve_declaration(state.pending_declarations[ally_id])
        if not combat_spatial_declarations.is_move(declaration):
            return False
        del state.pending_declarations[ally_id]
        turn[1] = None
        cursor.setdefault("cancelled_moves", []).append(ally_id)
        return True
    return False


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
    from condition_catalog import IRON_STANCE
    from conditions import remove_condition

    state.ally_continuation = cursor
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
                if actor is not None and actor.is_ally:
                    effects = await _packetless_turn_start(session, state, actor, progress, steps, packet_deps)
                    if fate_rolls.pending is not None:
                        state.beat = PhaseBeat.RESOLUTION
                        return summaries
                    if effects:
                        summaries.append({"actor_id": actor.id, "turn_start_effects": effects})
                if actor is not None:
                    actor.conditions = remove_condition(actor.conditions, IRON_STANCE)
                cancelled = cursor.get("cancelled_moves", [])
                if actor is not None and actor.id in cancelled:
                    cancelled.remove(actor.id)
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
        if summary.get("outcome") != "cancelled":
            await combat_field_medic.settle(
                session,
                state,
                packets[packet_id],
                summary,
                conn=packet_deps["conn"],
                sink=packet_deps["sink"],
                queries=packet_deps["queries"],
            )
        summaries.append(summary)
        cursor["attack"] = {}
        cursor.pop("steps", None)
        cursor["turns"].pop(0)

    state.held_actions = hold_enemy_packets(state, [packets[pid] for pid in cursor["hostiles"]])
    state.ally_continuation = None
    state.beat = PhaseBeat.NARRATION
    return summaries


async def _packetless_turn_start(
    session: "SessionData",
    state: "CombatState",
    actor: "CombatParticipant",
    progress: PacketRolls | None,
    steps: dict,
    packet_deps: dict,
) -> list[dict]:
    import choir_encounter
    import combat_veilrender

    if "turn_start_effects" not in steps:
        effects = await combat_veilrender.turn_start(
            session,
            state,
            actor,
            progress=progress.scope("veilrender") if progress is not None else None,
            **packet_deps,
        )
        if effects is None:
            return []
        steps["turn_start_effects"] = effects
    await choir_encounter.turn_start(
        session,
        state,
        actor,
        conn=packet_deps["conn"],
        concentration_break_mod=packet_deps["concentration_break_mod"],
        sink=packet_deps["sink"],
        progress=progress.scope("choir_aura") if progress is not None else None,
    )
    return steps["turn_start_effects"]
