"""Beat 3 — the held enemy actions and their reaction windows (M29, story-016).

decision 46 / game_mechanics_combat.md:182-187: the DM narrates each enemy action, PAUSES for a
reaction window, and the engine holds enemy damage until each window closes. Sprint 45 resolved
every packet in one pass, so the blow was written before the DM spoke. This module is the hold.

TWO WINDOWS PER ENEMY ATTACK, because story-018 needs both on the same blow: a PRE-ROLL window
(on_targeted / on_ally_targeted / on_enemy_action) and a POST-ROLL, PRE-DAMAGE window
(on_hit / on_ally_hit / on_enemy_miss / on_enemy_action, plus on_condition_imposed on a landed
grapple). The window VOCABULARY is reaction_windows.py's — a pure function of the action. The
PAUSE GATE is here, because it reads ``reactions_available``: gm_combat:131, "if the player has no
reaction abilities, the DM doesn't pause — narration flows continuously." Without that gate a
three-enemy round opens six windows the party cannot consume after its first spend.

The queue is stepped by ``resolve_phase``, one pause per call — no new verb (the open window
reaches the DM through the result's ``next`` field, ADR 0008 decision 4).
"""

import logging

import combat_enhancers
import reaction_windows
from combat_ability import _find_action
from combat_packet import _resolve_one_packet
from combat_support import deserialize_roll, roll_attack, serialize_roll
from declarations import DeclarationType, resolve_declaration

logger = logging.getLogger("divineruin.tools")

# The stages a held action passes through, in order. Recorded on the held entry (``opened``) so a
# window is offered exactly once per stage — a non-attack action has no roll to mark its progress,
# so the roll alone cannot serve as the position marker.
PRE_ROLL = "pre_roll"
POST_ROLL = "post_roll"


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
            "opened": [],
        }
        for seq, packet in enumerate(packets)
    ]


def pause_allowed(state) -> bool:
    """Can ANY standing player still spend a reaction this round? (AC9, gm_combat:131.)

    Reads ``reactions_available`` only. That map records whether the round's one reaction is
    SPENT, not whether the character owns any — the ownership half needs the ability catalog per
    member at the DECLARATION beat and is recorded as debt, not faked here. A fallen player's
    stale True must not hold the beat: a downed character cannot react.
    """
    return any(
        state.reactions_available.get(p.id, False) for p in state.participants if p.type == "player" and not p.is_fallen
    )


def _held_declaration(head: dict):
    return resolve_declaration(head["declaration"])


def _is_wasted(state, head: dict) -> bool:
    """A held action nobody can carry out: its actor fell to the ally band, or its target is gone.

    Such an action never opens a window — pausing on a no-op is the same noise AC9 prevents. It
    still POPS through the normal resolver, which produces trunk's own "actor unavailable" /
    "already fell" summary.
    """
    actor = state.get_participant(head["actor_id"])
    if actor is None or actor.is_fallen:
        return True
    declaration = _held_declaration(head)
    if declaration.type is not DeclarationType.ATTACK:
        return False
    target = state.get_participant(declaration.target_id) if declaration.target_id else None
    return target is None or target.is_fallen


def _attack_action(state, head: dict) -> dict | None:
    """The action_pool entry this held action swings, or None when it is not a plain attack.

    An enemy action carrying ``applies_condition`` (Hollow Shriek) resolves through the
    save-gated condition path, not an attack roll, so it gets the PRE-ROLL window only — which is
    exactly how bard_countercharm / diplomat_countercharm (on_ally_targeted) reach it. Same for
    DEFEND and any other non-attack declaration: no roll to hold, and the post-roll vocabulary is
    attack-shaped.
    """
    declaration = _held_declaration(head)
    if declaration.type is not DeclarationType.ATTACK:
        return None
    actor = state.get_participant(head["actor_id"])
    action = _find_action(actor, declaration.action) if actor is not None else None
    if action is None or action.get("applies_condition"):
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

    def _resolve(attacker_data, action, target_ac, target_hp, attack_mod=0, damage_mult=1.0):
        if target_ac != held_ac:
            raise ValueError(
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
        raise ValueError(
            f"held enemy action {action.get('name')!r} for {head['actor_id']!r} expands to "
            f"{len(swings)} swings; Beat 3 holds a single swing per window, so swings 2+ would "
            "land with no reaction window"
        )


async def pump(session, state, *, packet_deps: dict) -> list[dict]:
    """Step the Beat-3 queue until it pauses on a window or the queue drains.

    Returns the resolution summaries produced by THIS call. When it returns with
    ``state.open_window`` set, the caller commits and hands the window to the DM; when it returns
    with the queue empty, the caller runs Beat 4 in that same commit (AC6 — the wrap fires once,
    in the last commit, because an enemy blow can be what ends the fight).
    """
    # The DM came back, so whatever window we were paused on has closed.
    state.open_window = None
    summaries: list[dict] = []

    while state.held_actions:
        head = state.held_actions[0]
        action = None if _is_wasted(state, head) else _attack_action(state, head)

        if not _is_wasted(state, head):
            if PRE_ROLL not in head["opened"]:
                head["opened"].append(PRE_ROLL)
                if pause_allowed(state):
                    _open(state, head, PRE_ROLL, reaction_windows.pre_roll_triggers(action or {}))
                    return summaries

            if action is not None and head["roll"] is None:
                _assert_single_swing(state, head, action)
                head["roll"] = serialize_roll(*_roll(state, head, action, packet_deps["resolver"]))

            if head["roll"] is not None and POST_ROLL not in head["opened"]:
                head["opened"].append(POST_ROLL)
                if pause_allowed(state):
                    hit = head["roll"]["attack_result"]["hit"]
                    _open(state, head, POST_ROLL, reaction_windows.post_roll_triggers(action or {}, hit=hit))
                    return summaries

        summaries.append(await _resolve_held(session, state, head, packet_deps=packet_deps))
        state.held_actions.pop(0)

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
        target_ac_bonus=state.ac_modifiers.get(target.id, 0),
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
    return await _resolve_one_packet(session, state, packet, **deps)
