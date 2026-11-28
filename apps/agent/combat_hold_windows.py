"""Build and publish reaction windows for the current held strike."""

import logging

import event_types as E
import reaction_gate
import reaction_windows
from action_contracts_still import STILL_ZONE_KINDS
from combat_ability import _find_action
from combat_attack_roll import deserialize_roll
from combat_hold_actions import _held_declaration
from dice_roll_payloads import build_attack_dice_roll_payload
from encounter_actions import action_kind
from patron_zero_hp import provisional_ward_verdict
from reaction_windows import POST_REACTION_MISS, POST_ROLL, PRE_ROLL

logger = logging.getLogger("divineruin.tools")


def _window(state, head: dict, stage: str, triggers: tuple[str, ...]) -> dict:
    declaration = _held_declaration(head)
    actor = state.get_participant(head["actor_id"])
    action = _find_action(actor, declaration.action) if actor is not None else None
    if action is None:
        raise ValueError(f"held action {declaration.action!r} for {head['actor_id']!r} is unavailable")
    return reaction_windows.open_window_for(
        round_number=state.round_number,
        seq=head["seq"],
        stage=stage,
        actor_id=head["actor_id"],
        target_id=declaration.target_id,
        action_kind=action_kind(action),
        triggers=triggers,
    )


def open_window(state, candidate: dict) -> None:
    state.open_window = candidate
    logger.info(
        "beat 3: paused on %s window %s (%s -> %s)",
        candidate["stage"],
        candidate["id"],
        candidate["actor_id"],
        candidate["target_id"],
    )


def offer_pre_roll(state, head: dict, window_action: dict, summaries: list[dict]) -> bool:
    if PRE_ROLL not in head["opened"]:
        head["opened"].append(PRE_ROLL)
        triggers = (
            (reaction_windows.CATCH_ALL,)
            if action_kind(window_action) in STILL_ZONE_KINDS
            else reaction_windows.pre_roll_triggers(window_action)
        )
        candidate = _window(state, head, PRE_ROLL, triggers)
        if reaction_gate.offers_for_window(state, candidate):
            if head.get("melee_approach", {}).get("closed_distance"):
                summaries.append({**head["melee_approach"], "attack_resolved": False, "attack_pending": True})
            open_window(state, candidate)
            return True
    return False


async def offer_post_roll(
    session, state, head: dict, action: dict | None, summaries: list[dict], packet_deps: dict
) -> bool:
    if head["roll"] is not None and POST_ROLL not in head["opened"]:
        head["opened"].append(POST_ROLL)
        hit = head["roll"]["attack_result"]["hit"]
        candidate = _window(state, head, POST_ROLL, reaction_windows.post_roll_triggers(action or {}, hit=hit))
        if reaction_gate.offers_for_window(state, candidate):
            attack_result, _effective_ac = deserialize_roll(head["roll"])
            attacker = state.get_participant(head["actor_id"])
            attack_result = await provisional_ward_verdict(
                session,
                state,
                candidate["target_id"],
                attack_result,
                packet_deps["queries"],
                action=action or {},
                conn=packet_deps["conn"],
            )
            await packet_deps["sink"].emit(
                session.room,
                E.DICE_ROLL,
                build_attack_dice_roll_payload(attacker, attack_result),
                event_bus=session.event_bus,
            )
            head["roll_published"] = True
            if head.get("melee_approach", {}).get("closed_distance"):
                summaries.append({**head["melee_approach"], "attack_resolved": False, "attack_pending": True})
            open_window(state, candidate)
            return True
    return False


def offer_reaction_miss(state, head: dict) -> bool:
    candidate = _window(state, head, POST_REACTION_MISS, ("on_enemy_miss",))
    if not reaction_gate.offers_for_window(state, candidate):
        return False
    head["opened"].append(POST_REACTION_MISS)
    open_window(state, candidate)
    return True
