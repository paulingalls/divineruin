"""Beat 3 — the held enemy actions and their reaction windows (M29, story-016).

decision 46 / game_mechanics_combat.md:182-187: the DM narrates each enemy action, PAUSES for a
reaction window, and the engine holds enemy damage until each window closes. Sprint 45 resolved
every packet in one pass, so the blow was written before the DM spoke. This module is the hold.

TWO WINDOWS PER ENEMY ATTACK, because story-018 needs both on the same blow: a PRE-ROLL window
(on_targeted / on_ally_targeted / on_enemy_action) and a POST-ROLL, PRE-DAMAGE window
(on_hit / on_ally_hit / on_enemy_miss / on_enemy_action, plus on_condition_imposed on a landed
grapple). The window VOCABULARY is reaction_windows.py's — a pure function of the action. The
PAUSE GATE is here, because it combines participant ownership with the round's reaction budget:
gm_combat:131, "if the player has no reaction abilities, the DM doesn't pause — narration flows
continuously." Without that gate a three-enemy round opens six unusable windows.

The queue is stepped by ``resolve_phase``, one pause per call — no new verb (the open window
reaches the DM through the result's ``next`` field, ADR 0008 decision 4).
"""

import logging

import combat_enhancers
import combat_reaction_effect
import event_types as E
import reaction_spend
import reaction_windows
from combat_ability import _find_action
from combat_packet import _resolve_one_packet
from combat_support import build_attack_dice_roll_payload, deserialize_roll, roll_attack, serialize_roll
from condition_restrictions import cannot_act
from declarations import DeclarationType, resolve_declaration
from encounter_actions import action_kind
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
    return [
        {
            "seq": seq,
            "actor_id": packet.actor_id,
            "initiative": packet.initiative,
            "declaration": dict(state.pending_declarations.get(packet.actor_id, {})),
            "roll": None,
            "roll_published": False,
            "opened": [],
        }
        for seq, packet in enumerate(packets)
    ]


def pause_allowed(state) -> bool:
    """Can ANY standing player still spend a reaction this round? (AC9, gm_combat:131.)

    ``CombatParticipant.has_reaction_ability`` records ownership; ``reactions_available`` records
    whether the round's one reaction is spent. A fallen player's stale unspent entry must not hold
    the beat: a downed character cannot react.

    Asks ``reaction_spend.is_spent``, never the entry's truthiness: since story-017 a spent
    reaction is a truthy RECORD, so a boolean test would report it available and keep pausing on
    windows the party can no longer consume.
    """
    return any(
        not reaction_spend.is_spent(state.reactions_available.get(p.id))
        for p in state.participants
        if p.type == "player"
        and not p.is_fallen
        and not cannot_act(p.conditions)
        and p.has_reaction_ability is not False
    )


def preflight_spend(state, actor_id: str, ability_id: str) -> dict:
    """Validate the paused-action binding and prepare its spend without mutating state.

    Separate from ``record_spend`` so every refusal happens before the resource write. The head of
    ``held_actions`` IS the paused action by construction of ``pump`` — checked rather than
    assumed, because a spend bound to the wrong blow is a defect story-018 would silently inherit.
    The check is an actor-id match, not a parse of the window id's ``r<round>-<seq>-<stage>``
    format: one declaration per actor per phase makes the actor unique, and parsing the id would
    make its format a contract reaction_spend deliberately refused to give it.
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


def _held_declaration(head: dict):
    return resolve_declaration(head["declaration"])


def _is_wasted(state, head: dict) -> bool:
    """A held action nobody can carry out: its actor fell or cannot act, or its target is gone.

    Such an action never opens a window — pausing on a no-op is the same noise AC9 prevents. It
    still POPS through the normal resolver, which produces trunk's own "actor unavailable" /
    "already fell" / "loses the phase" summary.
    """
    actor = state.get_participant(head["actor_id"])
    if actor is None or actor.is_fallen or cannot_act(actor.conditions):
        return True
    declaration = _held_declaration(head)
    if declaration.type is not DeclarationType.ATTACK:
        return False
    target = state.get_participant(declaration.target_id) if declaration.target_id else None
    return target is None or target.is_fallen


def _opens_windows(state, head: dict) -> bool:
    """Does this held action open reaction windows at all?

    Only a held action that NAMES A TARGET does. Every trigger the pre-roll window emits is a
    claim that someone was targeted (``on_targeted`` / ``on_ally_targeted``), so opening it for an
    enemy DEFEND — or any other untargeted declaration declare_phase accepts for an enemy — would
    ship a descriptor that contradicts itself: triggers saying a blow is coming beside a null
    ``target_id``, and a player burning the round's one reaction on a foe that merely braced
    (constraint 6). Such an action still POPS through the ordinary resolver, unpaused.

    Nothing reachable today is lost by this: an untargeted enemy action could only ever reach the
    ``on_enemy_action`` catch-all, whose four consumers the census already classifies as one
    post-roll row (whisper_implant_doubt, "when an enemy SUCCEEDS an attack") plus three
    inapplicable social rows. An enemy command (``encounter_actions`` kind "command") names the party
    member it orders the attack on, so it pauses here too, at the pre-roll stage only: it never rolls.
    """
    if _is_wasted(state, head):
        return False
    return _held_declaration(head).target_id is not None


def _attack_action(state, head: dict) -> dict | None:
    """The action_pool entry this held action swings, or None when it is not a plain attack.

    An enemy action carrying ``applies_condition`` (Hollow Shriek) resolves through the
    save-gated condition path, not an attack roll, so it gets the PRE-ROLL window only — which is
    exactly how bard_countercharm / diplomat_countercharm (on_ally_targeted) reach it. It still
    names a target, so ``_opens_windows`` lets it pause; an untargeted declaration does not. A command
    (``encounter_actions`` kind "command") is an order, not a swing, so it never rolls either.
    """
    declaration = _held_declaration(head)
    if declaration.type is not DeclarationType.ATTACK:
        return None
    actor = state.get_participant(head["actor_id"])
    action = _find_action(actor, declaration.action) if actor is not None else None
    if action is None or action.get("applies_condition") or action_kind(action) == "command":
        return None
    return action


def _replay_resolver(head: dict):
    """A resolver that returns the HELD roll instead of rolling a new one.

    The apply half runs through the untouched ``_resolve_one_packet``, so a held action resolves
    down exactly the trunk path — dramatic context, durability, riders, first_attack_resolved —
    rather than through a second copy of that branch that could drift from it (AC6).

    Fails loud if the effective AC has moved since the roll: the summary would otherwise report a
    target_ac the roll was never made against. Nothing in this card changes AC mid-pause; a future
    reaction that does (story-018) must re-roll or re-derive, never silently mismatch.
    """
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


async def pump(session, state, *, packet_deps: dict) -> list[dict]:
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
    reacted, reaction_packet = None, None
    if closed is not None and state.held_actions:
        reacted = state.held_actions[0]
        reaction_packet = combat_reaction_effect.close(
            state, reacted, closed, attack_action=_attack_action(state, reacted)
        )
        if reaction_packet is not None:
            summaries.append(reaction_packet)

    while state.held_actions:
        head = state.held_actions[0]
        summary_start = len(summaries)
        opens = _opens_windows(state, head)
        action = _attack_action(state, head) if opens else None

        try:
            if opens:
                if PRE_ROLL not in head["opened"]:
                    head["opened"].append(PRE_ROLL)
                    if pause_allowed(state):
                        _open(state, head, PRE_ROLL, reaction_windows.pre_roll_triggers(action or {}))
                        _assert_iteration_progress(state, head, summaries, summary_start)
                        return summaries

                if action is not None and head["roll"] is None:
                    _assert_single_swing(state, head, action)
                    head["roll"] = serialize_roll(*_roll(state, head, action, packet_deps["resolver"]))

                if head["roll"] is not None and POST_ROLL not in head["opened"]:
                    head["opened"].append(POST_ROLL)
                    if pause_allowed(state):
                        hit = head["roll"]["attack_result"]["hit"]
                        attack_result, _effective_ac = deserialize_roll(head["roll"])
                        attacker = state.get_participant(head["actor_id"])
                        await packet_deps["sink"].emit(
                            session.room,
                            E.DICE_ROLL,
                            build_attack_dice_roll_payload(attacker, attack_result),
                            event_bus=session.event_bus,
                        )
                        head["roll_published"] = True
                        _open(state, head, POST_ROLL, reaction_windows.post_roll_triggers(action or {}, hit=hit))
                        _assert_iteration_progress(state, head, summaries, summary_start)
                        return summaries

            summary = await _resolve_held(session, state, head, packet_deps=packet_deps)
        except HeldActionUnresolvable as exc:
            summary = {"actor_id": head["actor_id"], "resolved": False, "reason": str(exc)}
            logger.error("beat 3: held action for %s unresolved: %s", head["actor_id"], exc)
            summaries.append(summary)
            _assert_iteration_progress(state, head, summaries, summary_start)
            state.held_actions.pop(0)
            continue

        if head is reacted:
            combat_reaction_effect.record_shield_wear(reaction_packet, summary)
        summaries.append(summary)
        state.held_actions.pop(0)
        _assert_iteration_progress(state, head, summaries, summary_start)

    return summaries


def _roll(state, head: dict, action: dict, resolver):
    """Roll the held swing WITHOUT touching HP — the post-roll window is pre-damage."""
    declaration = _held_declaration(head)
    attacker = state.get_participant(head["actor_id"])
    target = state.get_participant(declaration.target_id)
    return roll_attack(
        attacker,
        action,
        target,
        target_ac_bonus=state.ac_modifiers.get(target.id, 0) + combat_reaction_effect.ac_bonus(state, head),
        enemies_remaining=sum(1 for p in state.participants if p.type == "enemy" and not p.is_fallen),
        is_first_attack_of_combat=not state.first_attack_resolved,
        resolver=resolver,
    )


def _open(state, head: dict, stage: str, triggers: tuple[str, ...]) -> None:
    declaration = _held_declaration(head)
    state.open_window = reaction_windows.open_window_for(
        round_number=state.round_number,
        seq=head["seq"],
        stage=stage,
        actor_id=head["actor_id"],
        target_id=declaration.target_id,
        triggers=triggers,
    )
    logger.info(
        "beat 3: paused on %s window %s (%s -> %s)",
        stage,
        state.open_window["id"],
        head["actor_id"],
        declaration.target_id,
    )


async def _resolve_held(session, state, head: dict, *, packet_deps: dict) -> dict:
    """Apply one held action through the ordinary packet resolver.

    A rolled attack replays its held roll (see ``_replay_resolver``); everything else — a wasted
    action, an enemy condition packet, a DEFEND — resolves with the live resolver exactly as it
    would have in the single-pass phase.
    """
    from combat_phase import ResolutionPacket

    packet = ResolutionPacket(
        actor_id=head["actor_id"],
        declaration=_held_declaration(head),
        initiative=head["initiative"],
    )
    deps = dict(packet_deps)
    if head["roll"] is not None:
        deps["resolver"] = _replay_resolver(head)
    return await _resolve_one_packet(
        session,
        state,
        packet,
        reaction_ac_bonus=combat_reaction_effect.ac_bonus(state, head),
        shield_reaction=combat_reaction_effect.shield_reaction(state, head),
        publish_roll=not head.get("roll_published", False),
        **deps,
    )
