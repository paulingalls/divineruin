"""Judge a foe from persisted attack attempts and land Valdris's radiant damage."""

from copy import deepcopy

from asyncpg import Connection
from livekit.agents.llm import ToolError

import combat_damage
import db_queries
import dice
import encounter_facts
import still_encounter
from combat_condition_landing import _land_condition_on_one
from combat_damage_results import AutomaticDamageResult
from combat_events import EventSink
from combat_participant import CombatParticipant
from combat_state import CombatState
from companion_profiles import get_companion_profile
from patron_combat_edges import SCALES_VERDICT, require_complete_round
from session_data import SessionData

NAME = "The Scale's Verdict"


def _living(participant: CombatParticipant) -> bool:
    return participant.hp_current > 0 and not participant.is_fallen and not participant.is_dead


def _judged_foe(state: CombatState, target_id: str | None) -> CombatParticipant:
    if target_id in still_encounter.hidden_ids(state):
        raise ToolError("An unrevealed Still anchor cannot be judged.")
    if target_id in still_encounter.protected_ids(state):
        raise ToolError("This foe is protected by the Still's anchors.")
    choir = state.choir_encounter
    if choir is not None and target_id == choir["owner_id"] and choir["phase"] != "exposed":
        raise ToolError("The Choir is protected until its core is exposed.")
    foe = state.get_participant(target_id) if target_id else None
    if foe is None or foe.is_ally or foe.is_structure or not _living(foe):
        raise ToolError(f"{NAME} requires a living hostile creature in this fight.")
    return foe


async def scales_verdict(
    session: SessionData, actor_id: str, *, target_id: str | None, conn: Connection, sink: EventSink
) -> tuple[CombatState, dict]:
    state = session.combat_state
    if state is None:
        raise ToolError(f"{NAME} can only be used in combat.")
    require_complete_round(state, SCALES_VERDICT)
    working = deepcopy(state)
    actor = working.get_participant(actor_id)
    if actor is None or actor.type != "player" or not _living(actor):
        raise ToolError(f"{NAME} requires a living acting player in this fight.")
    foe = _judged_foe(working, target_id)
    evidence = []
    for victim_id in encounter_facts.party_victims(working, foe.id):
        victim = working.get_participant(victim_id)
        if victim is not None:
            name = victim.name
        else:
            # Retained encounters can carry evidence from a different party roster.
            player = await db_queries.get_player(victim_id, conn=conn)
            name = player["name"] if player is not None else get_companion_profile(victim_id).name
        evidence.append({"id": victim_id, "name": name})

    verdict = "unjust" if evidence else "just"
    recipient = foe if evidence else actor
    roll = dice.roll("4d8" if evidence else "2d8")
    receipt = await combat_damage.apply_attack_result(
        session,
        actor,
        {"name": NAME, "magical": True},
        recipient,
        AutomaticDamageResult(roll.total, "radiant"),
        recipient.ac,
        combat_state=working,
        conn=conn,
        sink=sink,
        publish_roll=False,
    )

    stunned = False
    if evidence and _living(foe):
        stunned = _land_condition_on_one(working, foe.id, actor, "stunned", NAME, packet=receipt, duration=1)
        if stunned and working.beat in ("narration", "wrap") and working.wrap_continuation is None:
            # Preserve the stun through the imminent wrap. A paused wrap has already ticked.
            next(condition for condition in foe.conditions if condition["type"] == "stunned")["inflicted_round"] = (
                working.round_number
            )

    evidence_cue = (
        "attacked " + ", ".join(victim["name"] for victim in evidence)
        if evidence
        else "attacked no party member or companion"
    )
    outcome = "dies" if recipient.is_dead else "falls" if recipient.is_fallen else "stays standing"
    if stunned:
        outcome += " and is Stunned for one round"
    cue = [
        f"Voice Valdris with [GOD_VALDRIS, stern]. {foe.name} is {verdict}. {foe.name} {evidence_cue}.",
        f"{roll.notation} rolled {roll.total}. {recipient.name} takes {receipt['damage']} radiant and {outcome}.",
    ]
    if receipt.get("temp_hp_absorbed"):
        cue.append(f"{receipt['temp_hp_absorbed']} temporary HP absorbed damage.")
    if receipt.get("gift_triggered"):
        cue.append(f"{receipt['dm_cue']} {recipient.name} has {recipient.hp_current} HP.")
    return working, {
        **receipt,
        "verdict": verdict,
        "judged_target": {"id": foe.id, "name": foe.name},
        "evidence": evidence,
        "roll": {"notation": roll.notation, "total": roll.total},
        "damage_recipient": {"id": recipient.id, "name": recipient.name},
        "target_dead": recipient.is_dead,
        "stunned": stunned,
        "dm_cue": " ".join(cue),
    }
