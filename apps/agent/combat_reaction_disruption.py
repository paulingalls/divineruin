"""Settle disruption saves and replacement attack rolls on the held strike."""

from dataclasses import asdict, replace
from functools import partial

import ability_voice_rules
import check_resolution_attack
import combat_hold_windows
import combat_reaction_effect
import event_types as E
from ability_voice_rules import DISSONANT_WHISPER, IMPLANT_DOUBT
from check_resolution_save import roll_participant_save
from combat_ability_save import player_ability_dc
from combat_attack_roll import (
    build_attack_dice_roll_payload,
    deserialize_roll,
    promote_attack,
    serialize_roll,
)
from combat_fate_rolls import PacketRolls, PhaseRolls, packet_save
from combat_legendary_resistance import finalize_save, override_fields
from combat_state import CombatState
from reaction_windows import POST_ROLL, PRE_ROLL
from session_data import SessionData

SAVE_ATTRIBUTES = {DISSONANT_WHISPER: "charisma", IMPLANT_DOUBT: "intelligence"}


def defer(
    state: CombatState, head: dict, packets: list[dict], hesitation_reason: str | None, attack_action: dict | None
) -> list[dict]:
    remaining, disruptions = [], []
    for packet in packets:
        ability = packet["ability_id"]
        if ability not in SAVE_ATTRIBUTES:
            remaining.append(packet)
        elif hesitation_reason is not None:
            remaining.append({**packet, "reason": hesitation_reason})
        elif attack_action is None:
            remaining.append({**packet, "reason": f"{packet['ability_name']} only answers enemy attack rolls."})
        elif ability == IMPLANT_DOUBT and "attack_context" not in head:
            remaining.append({**packet, "reason": "The original attack has no saved reroll context."})
        elif not ability_voice_rules.reaction_effect_eligible(
            state, head, state.reactions_available[packet["actor_id"]]
        ):
            remaining.append({**packet, "reason": "The attacker cannot hear Dissonant Whisper."})
        else:
            disruptions.append({"packet": packet})
    if not disruptions:
        return remaining
    # JSONB can reorder object keys. The spend ordinal survives that round trip.
    disruptions.sort(key=lambda entry: state.reactions_available[entry["packet"]["actor_id"]].get("order", 0))
    head["disruptions"] = disruptions
    head.setdefault("pending_reaction_packets", []).extend(remaining)
    return []


async def settle(
    session: SessionData, state: CombatState, head: dict, stage: str, deps: dict, fate: PhaseRolls | None
) -> bool:
    entries = head.get("disruptions")
    if not entries or entries[0]["packet"]["stage"] != stage:
        return True
    for entry in entries:
        if entry.get("complete"):
            continue
        packet = entry["packet"]
        if stage == POST_ROLL and not head["roll"]["attack_result"]["hit"]:
            packet["reason"] = "The attack already misses."
        else:
            if "save_success" not in packet and not await _save(session, state, head, entry, deps, fate):
                return False
            if not packet["save_success"]:
                if stage == PRE_ROLL:
                    head["attack_disadvantage_source"] = packet["ability_name"]
                    packet["mechanical_effect"] = "attack_disadvantage"
                else:
                    if not await _reroll(session, state, head, entry, deps, fate):
                        return False
                    packet["mechanical_effect"] = "attack_rerolled"
        entry["complete"] = True
    # Read from the head, not this call: earlier calls may have completed the reroll that missed.
    turned_miss = (
        stage == POST_ROLL
        and not head["roll"]["attack_result"]["hit"]
        and any(entry["packet"].get("mechanical_effect") == "attack_rerolled" for entry in entries)
    )
    if stage == POST_ROLL:
        combat_reaction_effect.settle_disruption_defenses(state, head)
    head["pending_reaction_packets"].extend(entry["packet"] for entry in entries)
    del head["disruptions"]
    if turned_miss and combat_hold_windows.offer_reaction_miss(state, head):
        result, _ = deserialize_roll(head["roll"])
        attacker = state.get_participant(head["actor_id"])
        await deps["sink"].emit(
            session.room, E.DICE_ROLL, build_attack_dice_roll_payload(attacker, result), event_bus=session.event_bus
        )
        head["roll_published"] = True
        return False
    return True


async def _save(
    session: SessionData, state: CombatState, head: dict, entry: dict, deps: dict, fate: PhaseRolls | None
) -> bool:
    attacker = state.get_participant(head["actor_id"])
    packet = entry["packet"]
    reactor = state.get_participant(packet["actor_id"])
    assert attacker is not None and reactor is not None
    dc = player_ability_dc(reactor, SAVE_ATTRIBUTES[packet["ability_id"]])
    effect = packet["ability_name"]
    progress = (
        PacketRolls(fate, entry.setdefault("roll_steps", {}), deps["queries"], deps["conn"])
        if fate is not None
        else None
    )
    result = await packet_save(
        progress,
        session,
        attacker.id,
        effect,
        partial(
            roll_participant_save,
            attacker,
            "wis",
            dc,
            effect,
            originating_participant_id=reactor.id,
            combat_state=state,
        ),
        state=state,
        queries=deps["queries"],
        conn=deps["conn"],
    )
    if result is None:
        return False
    result = finalize_save(state, attacker, result)
    packet.update(
        save_type=result.save_type,
        save_dc=result.dc,
        save_roll=result.roll,
        save_modifier=result.modifier,
        save_total=result.total,
        save_success=result.success,
        **override_fields(result),
        **result.oath_fields(),
    )
    if result.success:
        packet["reason"] = "The attacker resisted the disruption."
    return True


async def _reroll(
    session: SessionData, state: CombatState, head: dict, entry: dict, deps: dict, fate: PhaseRolls | None
) -> bool:
    context = head["attack_context"]
    _, ac = deserialize_roll(head["roll"])
    attacker = state.get_participant(head["actor_id"])
    target = state.get_participant(head["declaration"]["target_id"])
    assert attacker is not None and target is not None
    if "reroll" in entry:
        assert fate is not None
        prepared = check_resolution_attack.PreparedAttack.from_dict(entry.pop("reroll"))
        kept = fate.select(prepared.original)
    else:
        original = check_resolution_attack.PreparedAttack.from_dict(context["prepared"])
        d20 = replace(original.d20, dc=ac, disadvantage=True)
        prepared = replace(
            original, d20=d20, original=d20.roll(), attack_disadvantage_source=entry["packet"]["ability_name"]
        )
        kept = prepared.original
        if fate is not None and await fate.hold(
            session, "attack", attacker.id, kept, d20, queries=deps["queries"], conn=deps["conn"]
        ):
            entry["reroll"] = {**asdict(prepared), "consumed": list(prepared.consumed)}
            return False
    result = check_resolution_attack.finish_attack(
        context["attacker_data"],
        head["executed_action"],
        ac,
        target.hp_current,
        prepared,
        kept,
        damage_mult=attacker.damage_mult,
        target_conditions=target.conditions,
    )
    result = promote_attack(
        result,
        sum(1 for p in state.participants if p.type == "enemy" and not p.is_fallen),
        not state.first_attack_resolved,
    )
    head["roll"] = serialize_roll(result, ac)
    # The damage resolver can now publish the kept result after reductions and redirection.
    head["roll_published"] = False
    return True
