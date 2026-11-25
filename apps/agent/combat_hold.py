"""Beat 3 — the held enemy actions and their reaction windows (M29, story-016).

decision 46 / game_mechanics_combat.md:182-187: the DM narrates each enemy action, PAUSES for a
reaction window, and the engine holds enemy damage until each window closes. Sprint 45 resolved
every packet in one pass, so the blow was written before the DM spoke. This module is the hold.

Two stages can offer windows on one attack: a PRE-ROLL window
(on_targeted / on_ally_targeted / on_enemy_action) and a POST-ROLL, PRE-DAMAGE window
(on_hit / on_ally_hit / on_enemy_miss / on_enemy_action, plus on_condition_imposed on a landed
grapple). The window VOCABULARY is reaction_windows.py's — a pure function of the action. The
pause decision uses reaction_gate's activation rules for each candidate stage, per
gm_combat:131: narration flows when no player can react.

The queue is stepped by ``resolve_phase``, one pause per call — no new verb (the open window
reaches the DM through the result's ``next`` field, ADR 0008 decision 4).
"""

import logging
from uuid import uuid4

import architect_actions
import combat_enhancers
import combat_marks as combat_marks
import combat_melee_approach
import combat_reaction_contest
import combat_reaction_effect
import event_types as E
import reaction_gate
import reaction_spend
import reaction_windows
import thyra_thornwall
from action_contracts_still import STILL_ZONE_KINDS
from combat_ability import _find_action
from combat_attack_roll import build_attack_dice_roll_payload, deserialize_roll
from combat_fate_hostile import roll_hostile
from combat_fate_rolls import PacketRolls
from combat_hold_actions import (
    _attack_action,
    _held_declaration,
    _opens_windows,
)
from combat_hold_actions import (
    _is_wasted as _is_wasted,
)
from combat_multiattack import held_declarations, strike_summary
from combat_packet import _resolve_one_packet
from combat_reshape_packet import ReshapeRefused, resolve_reshape
from encounter_actions import action_kind
from patron_zero_hp import provisional_ward_verdict
from reaction_windows import POST_ROLL, PRE_ROLL

logger = logging.getLogger("divineruin.tools")


class HeldActionUnresolvable(ValueError):
    """A held action the engine can never resolve, so a retried phase would re-raise it forever.

    ``pump`` pops it as an unresolved summary instead of rolling the phase back — the only way the
    queue drains and ``end_combat`` stops refusing. Raising this type opts a failure into that
    tolerance; every other exception still rolls the phase back.
    """


def hold_enemy_packets(state, packets: list) -> list[dict]:
    """Build the Beat-3 queue from the hostile band's resolution packets.

    Each entry is JSONB-native so it round-trips through CombatState.to_dict/from_dict untouched:
    a crash between commits reloads to a paused combat, never to a deleted enemy turn (AC7).
    """
    queue = []
    for packet in packets:
        for declaration, provenance in held_declarations(state, packet):
            queue.append(
                {
                    "seq": len(queue),
                    "execution_id": uuid4().hex,
                    "actor_id": packet.actor_id,
                    "initiative": packet.initiative,
                    "declaration": declaration,
                    "roll": None,
                    "roll_published": False,
                    "opened": [],
                    **provenance,
                }
            )
    return queue


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
    return reaction_spend.spend(ability_id, state.open_window, held_seq=head["seq"])


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


def _assert_iteration_progress(state, head: dict, summaries: list[dict], summary_start: int) -> None:
    popped = not state.held_actions or state.held_actions[0] is not head
    unresolved = any(summary.get("resolved") is False for summary in summaries[summary_start:])
    opened = state.open_window is not None
    if not (popped or unresolved or opened):
        raise RuntimeError(f"held action for {head['actor_id']!r} made no progress")


async def pump(
    session, state, *, packet_deps: dict, contest_rng=None, fate_rolls=None, execution_id: str | None = None
) -> list[dict]:
    """Step the Beat-3 queue until it pauses on a window or the queue drains.

    Returns the resolution summaries produced by THIS call. When it returns with
    ``state.open_window`` set, the caller commits and hands the window to the DM; when it returns
    with the queue empty, the caller runs Beat 4 in that same commit (AC6 — the wrap fires once,
    in the last commit, because an enemy blow can be what ends the fight).
    """
    # The DM came back, so whatever window we were paused on has closed. Capture it on the way
    # out: a reaction spent at that window changes the held blow, and this is the one moment where
    # the spend exists and the blow has not been applied yet (story-018).
    closed, state.open_window = state.open_window, None
    summaries: list[dict] = []
    reacted, reaction_packets = None, []
    if closed is not None and state.held_actions:
        reacted = state.held_actions[0]
        reaction_packets = combat_reaction_effect.close(
            state, reacted, closed, attack_action=_attack_action(state, reacted), contest_rng=contest_rng
        )
        summaries.extend(reaction_packets)
        hesitation_reason = combat_reaction_contest.hesitation_reason(reacted)
        if hesitation_reason is not None:
            summaries.append(
                strike_summary(
                    reacted,
                    {
                        **reacted.get("melee_approach", {}),
                        "actor_id": reacted["actor_id"],
                        "attack_resolved": False,
                        "resolved": False,
                        "hesitated": True,
                        "reason": hesitation_reason,
                    },
                )
            )
            state.held_actions.pop(0)

    while state.held_actions:
        head = state.held_actions[0]
        if execution_id is not None and head.get("execution_id") != execution_id:
            break
        import choir_encounter
        from choir_effects import approach

        if execution_id is None:
            aura = None
            if fate_rolls is not None and session.fate_lock.locked() and state.choir_encounter is not None:
                aura = PacketRolls(
                    fate_rolls, head.setdefault("roll_steps", {}), packet_deps["queries"], packet_deps["conn"]
                ).scope("choir_aura")
            await choir_encounter.turn_start(
                session,
                state,
                state.get_participant(head["actor_id"]),
                conn=packet_deps.get("conn"),
                concentration_break_mod=packet_deps["concentration_break_mod"],
                progress=aura,
                sink=packet_deps.get("sink"),
            )
            if aura is not None and aura.paused:
                return summaries
            from combat_veilrender import turn_start

            field = None
            if fate_rolls is not None and session.fate_lock.locked():
                field = PacketRolls(
                    fate_rolls, head.setdefault("roll_steps", {}), packet_deps["queries"], packet_deps["conn"]
                ).scope("veilrender")
            effects = await turn_start(
                session, state, state.get_participant(head["actor_id"]), **{**packet_deps, "progress": field}
            )
            if effects is None:
                return summaries
            if effects:
                summaries.append({"actor_id": head["actor_id"], "turn_start_effects": effects})
            approach(state, state.get_participant(head["actor_id"]))
        progress = None
        declaration = _held_declaration(head)
        if declaration.reshape and fate_rolls is not None and (session.fate_lock.locked() or head.get("roll_steps")):
            progress = PacketRolls(
                fate_rolls, head.setdefault("roll_steps", {}), packet_deps["queries"], packet_deps["conn"]
            )
        try:
            ready = await resolve_reshape(
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
        summary_start = len(summaries)
        opens = _opens_windows(state, head)
        action = _attack_action(state, head) if opens else None
        if opens:
            actor = state.get_participant(head["actor_id"])
            movement = combat_melee_approach.prepare_held(
                state, head, _find_action(actor, _held_declaration(head).action)
            )
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
            if opens:
                if PRE_ROLL not in head["opened"]:
                    head["opened"].append(PRE_ROLL)
                    actor = state.get_participant(head["actor_id"])
                    window_action = _find_action(actor, _held_declaration(head).action)
                    assert window_action is not None
                    triggers = (
                        (reaction_windows.CATCH_ALL,)
                        if action_kind(window_action) in STILL_ZONE_KINDS
                        else reaction_windows.pre_roll_triggers(window_action)
                    )
                    candidate = _window(state, head, PRE_ROLL, triggers)
                    if reaction_gate.offers_for_window(state, candidate):
                        if head.get("melee_approach", {}).get("closed_distance"):
                            summaries.append(
                                {**head["melee_approach"], "attack_resolved": False, "attack_pending": True}
                            )
                        _open(state, candidate)
                        _assert_iteration_progress(state, head, summaries, summary_start)
                        return summaries

                if action is not None and head["roll"] is None:
                    if reason := architect_actions.slam_refusal(
                        state, head["actor_id"], action, head["declaration"]["target_id"]
                    ):
                        raise HeldActionUnresolvable(reason)
                    _assert_single_swing(state, head, action)
                    contribution = combat_reaction_effect.ac_bonus(state, head)
                    if not await roll_hostile(
                        session, state, head, _held_declaration(head), action, contribution, packet_deps, fate_rolls
                    ):
                        return summaries

                if head["roll"] is not None and POST_ROLL not in head["opened"]:
                    head["opened"].append(POST_ROLL)
                    hit = head["roll"]["attack_result"]["hit"]
                    candidate = _window(
                        state, head, POST_ROLL, reaction_windows.post_roll_triggers(action or {}, hit=hit)
                    )
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
                            summaries.append(
                                {**head["melee_approach"], "attack_resolved": False, "attack_pending": True}
                            )
                        _open(state, candidate)
                        _assert_iteration_progress(state, head, summaries, summary_start)
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
            summaries.append(strike_summary(head, _with_reshape(head, summary)))
            _assert_iteration_progress(state, head, summaries, summary_start)
            state.held_actions.pop(0)
            continue

        if fate_rolls is not None and fate_rolls.pending is not None:
            if head is reacted and reaction_packets:
                head["pending_reaction_packets"] = reaction_packets
                del summaries[: len(reaction_packets)]
            return summaries

        deferred_reactions = head.pop("pending_reaction_packets", [])
        recorded_reactions = reaction_packets if head is reacted else deferred_reactions
        if recorded_reactions:
            combat_reaction_effect.record_shield_wear(recorded_reactions, state, head, summary)
            combat_reaction_effect.record_save_advantage(recorded_reactions, summary)
        summaries.extend(deferred_reactions)
        summaries.append(strike_summary(head, _with_reshape(head, summary)))
        state.held_actions.pop(0)
        _assert_iteration_progress(state, head, summaries, summary_start)

    return summaries


def _with_reshape(head, summary):
    if receipts := head.get("reshape_receipts"):
        return {**summary, "reshape": receipts}
    return summary


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


def _open(state, candidate: dict) -> None:
    state.open_window = candidate
    logger.info(
        "beat 3: paused on %s window %s (%s -> %s)",
        candidate["stage"],
        candidate["id"],
        candidate["actor_id"],
        candidate["target_id"],
    )


async def _resolve_held(
    session, state, head: dict, *, packet_deps: dict, mark_cancelled: bool = False, fate_rolls=None
) -> dict:
    """Apply one held action through the ordinary packet resolver.

    A rolled attack replays its held roll (see ``_replay_resolver``); everything else — a wasted
    action, an enemy condition packet, a DEFEND — resolves with the live resolver exactly as it
    would have in the single-pass phase.
    """
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
    summary = await _resolve_one_packet(
        session,
        state,
        packet,
        reaction_ac_bonus=combat_reaction_effect.ac_bonus(state, head),
        reaction_save_advantage=combat_reaction_effect.save_advantage(
            state,
            head,
            ("charmed" if action_kind(action) == "charm" else action.get("applies_condition"))
            if action is not None
            else None,
        ),
        shield_reaction=combat_reaction_effect.shield_reaction(state, head),
        grapple_blocked=combat_reaction_effect.grapple_blocked(state, head),
        mark_cancelled=mark_cancelled,
        publish_roll=not head.get("roll_published", False),
        _held_head=head
        if "legendary_kind" in head or head.get("execution_receipt") is not None or "progress" in deps
        else None,
        _melee_approach=head.get("melee_approach"),
        _reshape_prepared=True,
        **deps,
    )
    # A paused (Zhael-held) resolution's summary is discarded by the pump; on resume the movement
    # facts join the finished summary.
    if movement := head.get("melee_approach"):
        summary = {**movement, **summary}
        if not summary["resolved"]:
            summary["attack_resolved"] = False
    return summary
