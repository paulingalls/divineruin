"""Durable ally turn boundaries, independent of action declarations."""

from livekit.agents.llm import ToolError

import architect_entomb
import combat_damage
import combat_damage_results
import combat_grapple
import combat_phase
import combat_regeneration
from combat_down import is_terminally_down
from condition_restrictions import cannot_act
from dice import roll as dice_roll


def validate_turn_start_damage(data):
    for participant in data["participants"]:
        effect = participant.get("turn_start_damage")
        if effect is not None and effect != {
            "trigger": "grappled_by_source",
            "damage": "1d6",
            "damage_type": "necrotic",
        }:
            raise ValueError(f"invalid turn-start damage for {participant['id']}")


def ally_turns(state, packets):
    by_id = {p.actor_id: p for p in packets}
    for actor in sorted(
        (p for p in state.participants if p.is_ally), key=combat_phase.resolution_sort_key, reverse=True
    ):
        yield actor, by_id.pop(actor.id, None)
    for packet in by_id.values():
        yield None, packet


async def turn_start(
    session, state, victim, *, conn, sink, mutations, queries, concentration_break_mod, progress=None, **unused
):
    packet = await _damage(
        session,
        state,
        victim,
        conn=conn,
        sink=sink,
        mutations=mutations,
        queries=queries,
        concentration_break_mod=concentration_break_mod,
        progress=progress,
    )
    if progress is not None and progress.paused:
        return None
    if not victim.is_dead and (chamber_id := architect_entomb.source(state, victim.id)):
        chamber = state.get_participant(chamber_id)
        assert chamber is not None
        compression = await _apply(
            session,
            state,
            victim,
            chamber,
            "Entomb compression",
            architect_entomb.COMPRESSION,
            conn=conn,
            sink=sink,
            mutations=mutations,
            queries=queries,
            concentration_break_mod=concentration_break_mod,
            progress=progress.scope("entomb") if progress is not None else None,
        )
        if progress is not None and progress.paused:
            return None
        if packet is None:
            packet = compression
        elif compression is not None:
            packet["turn_start_effects"] = [compression]
    effect = await combat_regeneration.tick(victim, conn=conn, mutations=mutations)
    if effect is not None:
        if packet is None:
            packet = {"actor_id": victim.id, "round": state.round_number}
        packet.setdefault("turn_start_effects", []).append(effect)
    return packet


async def _damage(session, state, victim, *, conn, sink, mutations, queries, concentration_break_mod, progress):
    # Once per round comes from the beat machine: Beat 2 commits with the move to NARRATION,
    # and Beat-3 pauses and reloads re-enter only combat_hold.pump, never this boundary.
    # A Hollowed echo is an already-dead player-life, outside the ally band.
    if not victim.is_ally or victim.is_dead or (victim.type == "player" and is_terminally_down(victim)):
        return None
    owner_id = combat_grapple.grappler_id(victim.conditions)
    if owner_id is None:
        return None
    owner = state.get_participant(owner_id)
    if owner is None:
        raise ToolError(f"{victim.id} grapple source {owner_id} is missing")
    if (
        owner.creature_id != "hollow_mawling"
        or owner.turn_start_damage is None
        or owner.hp_current <= 0
        or owner.is_fallen
        or is_terminally_down(owner)
        or cannot_act(owner.conditions)
    ):
        return None
    return await _apply(
        session,
        state,
        victim,
        owner,
        "Dissolution Field",
        owner.turn_start_damage,
        conn=conn,
        sink=sink,
        mutations=mutations,
        queries=queries,
        concentration_break_mod=concentration_break_mod,
        progress=progress,
    )


async def _apply(
    session, state, victim, owner, name, effect, *, conn, sink, mutations, queries, concentration_break_mod, progress
):
    if progress is not None and "summary" in progress.steps:
        return progress.steps["summary"]
    result = None
    if progress is None or "damage_receipt" not in progress.steps:
        damage = dice_roll(effect["damage"]).total
        result = combat_damage_results.AutomaticDamageResult(damage, effect["damage_type"])
    summary = await combat_damage.apply_attack_result(
        session,
        owner,
        {"name": name},
        victim,
        result,
        victim.ac,
        mutations=mutations,
        queries=queries,
        concentration_break_mod=concentration_break_mod,
        combat_state=state,
        conn=conn,
        sink=sink,
        publish_roll=False,
        progress=progress,
    )
    if progress is not None and progress.paused:
        return None
    if not victim.is_ally or victim.is_fallen or cannot_act(victim.conditions):
        state.ac_modifiers.pop(victim.id, None)
    packet = {
        **summary,
        "automatic": True,
        "actor_id": owner.id,
        "source_id": owner.id,
        "target_id": victim.id,
        "round": state.round_number,
    }
    if progress is not None:
        progress.steps["summary"] = packet
    return packet
