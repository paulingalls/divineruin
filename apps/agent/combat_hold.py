"""Beat 3 — the held enemy actions and their reaction windows (M29, story-016).

decision 46 / game_mechanics_combat.md:182-187: the DM narrates each enemy action, PAUSES for a
reaction window, and the engine holds enemy damage until each window closes. Sprint 45 resolved
every packet in one pass, so the blow was written before the DM spoke. This module is the hold.

Movement can pause at a warrior's reach before the roll. Attack windows can
pause before the roll or between its outcome and damage. A save-only restraint
can open a window after it takes hold.

The queue is stepped by ``resolve_phase``, one pause per call — no new verb (the open window
reaches the DM through the result's ``next`` field, ADR 0008 decision 4).
"""

import logging
from uuid import uuid4

import architect_actions
import combat_counter_reactions
import combat_enhancers
import combat_hold_conditions
import combat_hold_windows
import combat_marks as combat_marks
import combat_opportunity
import combat_reaction_contest
import combat_reaction_disruption
import combat_reaction_effect
import patron_synergy_combat
import reaction_spend
import thyra_thornwall
from combat_ability import _find_action
from combat_attack_roll import deserialize_roll
from combat_departure import cancel_held_strike, departed_target
from combat_fate_hostile import roll_hostile
from combat_fate_rolls import PacketRolls
from combat_hold_actions import (
    _attack_action,
    _held_declaration,
    _opens_windows,
    assert_iteration_progress,
    concealed_target_reason,
)
from combat_hold_actions import (
    _is_wasted as _is_wasted,
)
from combat_multiattack import held_declarations, strike_summary
from combat_packet import _resolve_one_packet
from combat_reaction_closure import close_window
from combat_reshape_packet import ReshapeRefused, resolve_reshape
from combat_turn_flight import is_flight_turn
from encounter_actions import action_kind
from reaction_windows import MOVEMENT, POST_ROLL, PRE_ROLL

logger = logging.getLogger("divineruin.tools")


class HeldActionUnresolvable(ValueError):
    """A held action the engine can never resolve, so a retried phase would re-raise it forever.

    ``pump`` pops it as an unresolved summary instead of rolling the phase back — the only way the
    queue drains and ``end_combat`` stops refusing. Raising this type opts a failure into that
    tolerance; every other exception still rolls the phase back.
    """


def new_head(state, actor_id: str, initiative: int, declaration: dict, **provenance) -> dict:
    seq = state.held_sequence
    state.held_sequence += 1
    return {
        "seq": seq,
        "execution_id": uuid4().hex,
        "actor_id": actor_id,
        "initiative": initiative,
        "declaration": declaration,
        "roll": None,
        "roll_published": False,
        "opened": [],
        **provenance,
    }


def hold_enemy_packets(state, packets: list) -> list[dict]:
    return [
        new_head(state, packet.actor_id, packet.initiative, declaration, **provenance)
        for packet in packets
        for declaration, provenance in held_declarations(state, packet)
    ]


def preflight_spend(state, actor_id: str, ability_id: str) -> dict:
    """Validate the paused-action binding and prepare its spend without mutating state.

    Separate from ``record_spend`` so every refusal happens before the resource write. The head of
    ``held_actions`` IS the paused action by construction of ``pump`` — checked rather than
    assumed, because a spend bound to the wrong blow is a defect story-018 would silently inherit.
    Composite sibling strikes share an actor id, so the actor match alone cannot tell them apart;
    it suffices because ``_open`` only ever opens the current head's window.
    """
    if state.open_window is None or not state.held_actions:
        raise ValueError(
            f"cannot prepare a reaction spend for {actor_id!r}: the machine is not paused on a "
            f"held action (open_window={state.open_window!r}, {len(state.held_actions)} held)"
        )
    head = state.held_actions[0]
    if state.open_window["actor_id"] != head["actor_id"]:
        raise ValueError(
            f"cannot prepare a reaction spend for {actor_id!r}: the open window answers "
            f"{state.open_window['actor_id']!r} but the queue head is {head['actor_id']!r}"
        )
    spend = reaction_spend.spend(ability_id, state.open_window, held_seq=head["seq"])
    if ability_id in combat_reaction_disruption.SAVE_ATTRIBUTES:
        spend["order"] = sum(entry["window_id"] == spend["window_id"] for entry in state.reactions_available.values())
    return spend


def record_spend(state, actor_id: str, spend: dict) -> None:
    """Install a preflighted spend as one non-awaiting field write."""
    state.reactions_available[actor_id] = spend


def _replay_resolver(head: dict):
    from combat_attack_roll import held_reaction_ac

    held_reaction_ac(head)
    attack_result, held_ac = deserialize_roll(head["roll"])

    def _resolve(attacker_data, action, target_ac, target_hp, attack_mod=0, damage_mult=1.0, target_conditions=()):
        if target_ac != held_ac:
            raise HeldActionUnresolvable(
                f"held roll for {head['actor_id']!r} was made against AC {held_ac}, but the target's "
                f"effective AC is now {target_ac} — the pause changed the roll's premise"
            )
        return attack_result

    class _Replay:
        resolve_attack = staticmethod(_resolve)
        mortaen_ac_bonus = attack_result.mortaen_ac_bonus
        orenthel_ac_bonus = attack_result.orenthel_ac_bonus
        nythera_ac_bonus = attack_result.nythera_ac_bonus

    return _Replay()


def _assert_single_swing(state, head: dict, action: dict) -> None:
    """No enemy in content carries ``enhancers`` — combat_init populates them only from
    players.data.flags — so a held enemy action is always ONE swing. Raise rather than resolve a
    multi-swing sequence whose swings 2+ would apply damage with no window (constraint 4)."""
    actor = state.get_participant(head["actor_id"])
    swings = combat_enhancers.attack_sequence(actor.enhancers if actor else [], action)
    if len(swings) > 1:
        raise HeldActionUnresolvable(
            f"held enemy action {action.get('name')!r} for {head['actor_id']!r} expands to "
            f"{len(swings)} swings; Beat 3 holds a single swing per window, so swings 2+ would "
            "land with no reaction window"
        )


async def pump(
    session, state, *, packet_deps: dict, contest_rng=None, fate_rolls=None, execution_id: str | None = None
) -> list[dict]:
    """Step the Beat-3 queue until it pauses on a window or the queue drains.

    Returns the resolution summaries produced by THIS call. When it returns with
    ``state.open_window`` set, the caller commits and hands the window to the DM; when it returns
    with the queue empty, the caller runs Beat 4 in that same commit (AC6 — the wrap fires once,
    in the last commit, because an enemy blow can be what ends the fight).
    """
    summaries: list[dict] = []
    closed, state.open_window = state.open_window, None
    while state.held_actions:
        head = state.held_actions[0]
        if execution_id is not None and head.get("execution_id") != execution_id:
            break
        window, closed = closed, None
        if target := _uncommitted_departed_target(state, head):
            if fate_rolls is not None:
                fate_rolls.kept = None
            summaries.append(cancel_held_strike(state, head, target))
            continue
        reacted, reaction_packets = None, []
        if window is not None and window["stage"] != MOVEMENT:
            reacted = head
            reason = await concealed_target_reason(state, head, _held_declaration(head), packet_deps=packet_deps)
            if reason is not None:
                summaries.extend(combat_reaction_effect.finish_thought_shield(head, {}))
                summaries.append(_concealed_summary(head, reason))
                state.held_actions.pop(0)
                continue
            reaction_packets, paused = await close_window(state, head, window, summaries, packet_deps, contest_rng)
            if paused:
                return summaries
            if not state.held_actions or state.held_actions[0] is not head:
                continue
        if continuation := head.get("counter_settlement"):
            if not await combat_counter_reactions.settle(session, state, head, summaries, packet_deps, fate_rolls):
                return summaries
            summary = continuation["attack"]
            del head["counter_settlement"]
            if _finish_strike(state, head, _attack_action(state, head), summary, summaries):
                return summaries
            continue
        if "completed_condition" in head:
            summaries.append(strike_summary(head, _with_reshape(head, head["completed_condition"])))
            state.held_actions.pop(0)
            continue
        if execution_id is None:
            from combat_turn_start import start_held_packet

            effects = await start_held_packet(session, state, head, fate_rolls, packet_deps)
            if effects is None:
                return summaries
            if effects:
                summaries.append({"actor_id": head["actor_id"], "turn_start_effects": effects})
        progress = None
        declaration = _held_declaration(head)
        if declaration.reshape and fate_rolls is not None and (session.fate_lock.locked() or head.get("roll_steps")):
            progress = PacketRolls(
                fate_rolls, head.setdefault("roll_steps", {}), packet_deps["queries"], packet_deps["conn"]
            )
        try:
            head_actor = state.get_participant(head["actor_id"])
            fleeing = head_actor is not None and is_flight_turn(head_actor, head)
            ready = fleeing or await resolve_reshape(
                session,
                state,
                head["actor_id"],
                declaration,
                head,
                progress=progress,
                packet_deps=packet_deps,
            )
        except ReshapeRefused as error:
            if execution_id is not None:
                raise
            summaries.append({"actor_id": head["actor_id"], "resolved": False, "reason": str(error)})
            state.held_actions.pop(0)
            continue
        if not ready:
            return summaries
        if head.get("legendary_kind") in ("shift_wall", "reshape"):
            summaries.append(_with_reshape(head, {"actor_id": head["actor_id"], "resolved": True}))
            state.held_actions.pop(0)
            continue
        if head is not reacted and (
            reason := await concealed_target_reason(state, head, declaration, packet_deps=packet_deps)
        ):
            summaries.append(_concealed_summary(head, reason))
            state.held_actions.pop(0)
            continue
        summary_start = len(summaries)
        opens = not fleeing and ("opportunity_approach" in head or _opens_windows(state, head))
        action = _attack_action(state, head) if opens else None
        window_action = None
        if opens:
            actor = state.get_participant(head["actor_id"])
            window_action = _find_action(actor, declaration.action)
            assert window_action is not None
            movement = {}
            if not head.get("opportunity_attack"):
                movement = await combat_opportunity.prepare_held(
                    session, state, head, window_action, summaries, packet_deps=packet_deps, fate_rolls=fate_rolls
                )
            if movement is None:
                return summaries
            if movement.get("attack_resolved") is False:
                movement = await thyra_thornwall.resolve_held_contact(
                    session, state, actor, movement, head, fate_rolls=fate_rolls, packet_deps=packet_deps
                )
                if movement is None:
                    return summaries
                summaries.append(strike_summary(head, _with_reshape(head, movement)))
                state.held_actions.pop(0)
                continue

        try:
            if window_action is not None:
                if combat_hold_windows.offer_pre_roll(state, head, window_action, summaries):
                    assert_iteration_progress(state, head, summaries, summary_start)
                    return summaries

                if "sidestep" in head:
                    receipt = await combat_counter_reactions.sidestep(
                        session, state, head, window_action, packet_deps, fate_rolls
                    )
                    if receipt is None:
                        return summaries
                    del head["sidestep"]
                    summaries.append(receipt)

                if not await combat_reaction_disruption.settle(session, state, head, PRE_ROLL, packet_deps, fate_rolls):
                    return summaries

                if action is not None and head["roll"] is None:
                    if reason := architect_actions.slam_refusal(
                        state, head["actor_id"], action, head["declaration"]["target_id"]
                    ):
                        raise HeldActionUnresolvable(reason)
                    if not head.get("opportunity_attack"):
                        _assert_single_swing(state, head, action)
                    contribution = combat_reaction_effect.ac_bonus(state, head)
                    if not await roll_hostile(
                        session, state, head, _held_declaration(head), action, contribution, packet_deps, fate_rolls
                    ):
                        return summaries

                if await combat_hold_windows.offer_post_roll(session, state, head, action, summaries, packet_deps):
                    assert_iteration_progress(state, head, summaries, summary_start)
                    return summaries

                if not await combat_reaction_disruption.settle(
                    session, state, head, POST_ROLL, packet_deps, fate_rolls
                ):
                    return summaries

            summary = await _resolve_held(
                session,
                state,
                head,
                packet_deps=packet_deps,
                mark_cancelled=combat_reaction_contest.mark_cancelled(head),
                fate_rolls=fate_rolls,
            )
        except HeldActionUnresolvable as exc:
            summary = {"actor_id": head["actor_id"], "resolved": False, "reason": str(exc)}
            logger.error("beat 3: held action for %s unresolved: %s", head["actor_id"], exc)
            summaries.extend(combat_reaction_effect.finish_thought_shield(head, summary))
            summaries.append(strike_summary(head, _with_reshape(head, summary)))
            assert_iteration_progress(state, head, summaries, summary_start)
            state.held_actions.pop(0)
            continue

        if fate_rolls is not None and fate_rolls.pending is not None:
            if head is reacted and reaction_packets:
                head.setdefault("pending_reaction_packets", []).extend(reaction_packets)
                del summaries[: len(reaction_packets)]
            return summaries

        deferred_reactions = head.pop("pending_reaction_packets", [])
        recorded_reactions = [*deferred_reactions, *(reaction_packets if head is reacted else [])]
        if recorded_reactions:
            combat_reaction_effect.record_settled(recorded_reactions, state, head, summary)
            damage = summary.get("damage", 0)
            await patron_synergy_combat.restore_guard_stamina(
                recorded_reactions, queries=packet_deps["queries"], conn=packet_deps["conn"], damage=damage
            )
        if any(packet["ability_id"] in reaction_spend.COUNTERS for packet in deferred_reactions):
            head["counter_settlement"] = {"attack": summary, "packets": deferred_reactions}
            continue
        summaries.extend(deferred_reactions)
        paused = _finish_strike(state, head, window_action, summary, summaries)
        assert_iteration_progress(state, head, summaries, summary_start)
        if paused:
            return summaries

    return summaries


def _uncommitted_departed_target(state, head: dict) -> str | None:
    if not state.departed_player_ids or "counter_settlement" in head or "completed_condition" in head:
        return None
    return head.get("departed_damage_recipient") or departed_target(state, _held_declaration(head))


def _finish_strike(state, head: dict, action: dict | None, summary: dict, summaries: list[dict]) -> bool:
    summaries.extend(combat_reaction_effect.finish_thought_shield(head, summary))
    if action is not None and (candidate := combat_hold_conditions.window_for(state, head, action, summary)):
        head["completed_condition"] = summary
        head["opened"].append(POST_ROLL)
        combat_hold_windows.open_window(state, candidate)
        return True
    summaries.append(strike_summary(head, _with_reshape(head, summary)))
    state.held_actions.pop(0)
    return False


def _concealed_summary(head: dict, reason: str) -> dict:
    return strike_summary(
        head, _with_reshape(head, {"actor_id": head["actor_id"], "resolved": False, "reason": reason})
    )


def _with_reshape(head, summary):
    if receipts := head.get("reshape_receipts"):
        return {**summary, "reshape": receipts}
    return summary


async def _resolve_held(
    session, state, head: dict, *, packet_deps: dict, mark_cancelled: bool = False, fate_rolls=None
) -> dict:
    """Apply one held action through the ordinary packet resolver.

    A rolled attack replays its held roll (see ``_replay_resolver``); everything else — a wasted
    action, an enemy condition packet, a DEFEND — resolves with the live resolver exactly as it
    would have in the single-pass phase.
    """
    from combat_attack_roll import shield_of_faith_ac
    from combat_phase import ResolutionPacket

    declaration = _held_declaration(head)
    packet = ResolutionPacket(
        actor_id=head["actor_id"],
        declaration=declaration,
        initiative=head["initiative"],
    )
    attacker = state.get_participant(head["actor_id"])
    action = _find_action(attacker, declaration.action) if attacker is not None else None
    deps = dict(packet_deps)
    if head["roll"] is not None:
        deps["resolver"] = _replay_resolver(head)
    if fate_rolls is not None and (session.fate_lock.locked() or head.get("roll_steps")):
        deps["progress"] = PacketRolls(fate_rolls, head.setdefault("roll_steps", {}), deps["queries"], deps["conn"])
    damage_target = combat_reaction_effect.intercept_target(state, head)
    reaction_ac_bonus = combat_reaction_effect.ac_bonus(state, head)
    if "shield_of_faith_ac" in head:
        # Departure ends the ward while the already-rolled strike retains its AC.
        target = state.get_participant(declaration.target_id or "")
        live_ward = shield_of_faith_ac(target.conditions if target is not None else [])
        reaction_ac_bonus += head["shield_of_faith_ac"] - live_ward
    summary = await _resolve_one_packet(
        session,
        state,
        packet,
        reaction_ac_bonus=reaction_ac_bonus,
        reaction_save_advantage=combat_reaction_effect.save_advantage(
            state,
            head,
            ("charmed" if action_kind(action) == "charm" else action.get("applies_condition"))
            if action is not None
            else None,
        ),
        shield_reaction=combat_reaction_effect.shield_reaction(state, head),
        psychic_shield_id=combat_reaction_effect.psychic_shield_id(state, head),
        damage_target=damage_target,
        grapple_blocked=combat_reaction_effect.grapple_blocked(state, head),
        mark_cancelled=mark_cancelled,
        publish_roll=not head.get("roll_published", False),
        _held_head=head
        if head.get("opportunity_attack")
        or "legendary_kind" in head
        or head.get("execution_receipt") is not None
        or "progress" in deps
        else None,
        _melee_approach={} if head.get("opportunity_attack") else head.get("melee_approach"),
        _reshape_prepared=True,
        **deps,
    )
    if (
        damage_target is not None
        and (fate_rolls is None or fate_rolls.pending is None)
        and summary.get("damage_target_id") != damage_target.id
    ):
        raise ValueError(f"Intercepted hit did not settle damage on {damage_target.id!r}")
    # A paused (Zhael-held) resolution's summary is discarded by the pump; on resume the movement
    # facts join the finished summary.
    if movement := head.get("melee_approach"):
        summary = {**movement, **summary}
        if not summary["resolved"]:
            summary["attack_resolved"] = False
    return summary
