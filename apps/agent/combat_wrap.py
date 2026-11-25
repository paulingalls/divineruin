"""Beat 4 — the phase wrap, and the ``next`` envelope the DM reads (M29, story-016).

Both pieces belong to the END of a round rather than to its orchestration:
``_wrap_phase`` runs exactly once per round, in the LAST commit, and ``next_envelope`` says what
the DM does after whichever commit just landed.
"""

from dataclasses import asdict
from functools import partial

import combat_grapple
import combat_hollow_resonance
import combat_phase
import combat_recharge
import concealment
import conditions
import event_types as E
import fatigue_narration
import reaction_gate
from combat_ability import _find_action
from combat_end import _end_combat_db
from combat_events import emit_or_publish
from combat_fate_rolls import PhaseRolls
from combat_ui_update import build_combat_ui_update
from condition_restrictions import cannot_act
from declarations import DeclarationType, resolve_declaration
from session_data import SessionData


def _held_action_name(state) -> str | None:
    head = state.held_actions[0]
    declaration = resolve_declaration(head["declaration"])
    actor = state.get_participant(head["actor_id"])
    action = _find_action(actor, declaration.action) if actor is not None else None
    if action is not None:
        return action["name"]
    if declaration.type is DeclarationType.ATTACK:
        raise ValueError(f"held attack action {declaration.action!r} for {head['actor_id']!r} is unavailable")
    return None


def next_envelope(state) -> dict:
    """What the DM does next: the phase, the verb that ADVANCES it, and the open window (ADR 0008 d4).

    This is the window PRODUCER (constraint 6): rather than the DM guessing among the nine
    abilities.REACTION_WINDOWS, the engine names the window it is paused on, and the DM passes back
    an id it minted.

    ``verbs`` is the ADVANCE set, not a whitelist of everything legal right now, and the prompt
    says so: the same result payload carries ``death_saves_due`` and ``legendary_available``, whose
    verbs (request_death_save, consume_legendary_action) have no beat gate and are still owed at
    the very moment ``verbs`` reads ``["declare_phase"]``. Reading it as exhaustive would have the
    DM skip a downed player's death save — so it names the move that steps the machine, and
    nothing more.

    ``activate`` IS legal at an open window since story-017 — validate_reaction_activation gates
    on this very ``open_window`` — and it is still deliberately ABSENT from ``verbs``, because
    ``verbs`` names the ADVANCE move and only resolve_phase advances a paused beat. The producer
    for activation is ``waiting_on.reactions``: the exact reaction ids this window accepts, named
    by the same gate activation enforces, so the DM never guesses an id (constraint 6). Listing a
    non-advancing verb here would contradict the "not a whitelist" reading in the same payload.
    """
    if state.open_window is not None:
        window = state.open_window
        head = state.held_actions[0]
        return {
            "phase": state.beat,
            "verbs": ["resolve_phase"],
            "waiting_on": {
                "window_id": window["id"],
                "stage": window["stage"],
                "actor_id": window["actor_id"],
                "target_id": window["target_id"],
                "triggers": window["triggers"],
                "action": _held_action_name(state),
                "reactions": reaction_gate.offered_reactions(state),
                **(
                    {"opportunity_attack": True, "interrupt_position": head["interrupt_position"]}
                    if head.get("opportunity_attack")
                    else {}
                ),
            },
        }
    if state.legendary_continuation is not None or state.beat == combat_phase.PhaseBeat.NARRATION:
        return {"phase": state.beat, "verbs": ["resolve_phase"], "waiting_on": None}
    return {
        "phase": "declaration",
        "verbs": ["declare_phase"],
        "waiting_on": None,
        "cannot_act": [
            {"actor_id": p.id, "name": p.name, "conditions": list(blocked)}
            for p in state.participants
            if (blocked := cannot_act(p.conditions))
        ],
        "prone": [
            {"actor_id": p.id, "name": p.name}
            for p in state.participants
            if not p.is_fallen and conditions.has_condition(p.conditions, "prone")
        ],
        "grappled": [
            {"actor_id": p.id, "name": p.name, "grappler_id": grappler}
            for p in state.participants
            if not p.is_fallen and (grappler := combat_grapple.grappler_id(p.conditions)) is not None
        ],
    }


def _roll_tick_save(state, actor, event, save_resolver):
    # Clearing saves predate proficiency and never consume a limited-use bonus die.
    return save_resolver.roll_participant_save(
        actor,
        event["save"],
        10,
        event["type"],
        bonus_dice_eligible=False,
        include_proficiency=False,
        originating_participant_id=event.get("originating_participant_id"),
        combat_state=state,
    )


async def wrap_phase(
    session: SessionData,
    state,
    *,
    conn,
    sink,
    cast_outcome,
    mutations,
    queries,
    save_resolver,
    resonance_mutations,
    fate_rolls=None,
) -> tuple:
    """Advance to wrap once, then drain clearing saves before round finalization.

    Wrap rides the LAST commit of the phase rather than the first because an enemy blow can be
    what ends the fight, so the end-condition cannot be computed before the enemies have acted.
    """
    fate_rolls = fate_rolls if fate_rolls is not None else PhaseRolls()
    end_data: dict | None = None
    cursor = state.wrap_continuation
    if cursor is None:
        state, _ = combat_phase.advance_combat_phase(state)
        # Read exhaustion narration here, before the pure wrap tick, so a save-to-clear tick
        # cannot erase a participant's narration mid-beat.
        exhaustion_narration = {
            p.id: narrative
            for p in state.participants
            if (narrative := fatigue_narration.exhaustion_narrative_for_conditions(p.conditions))
        }
        state, wrap_adv = combat_phase.advance_combat_phase(state, defer_legendary=True)
        assert wrap_adv.wrap is not None
        wrap = wrap_adv.wrap
        cursor = {"wrap": asdict(wrap), "exhaustion": exhaustion_narration, "index": 0}
    else:
        wrap = combat_phase.WrapOutcome(**cursor["wrap"])
        exhaustion_narration = cursor["exhaustion"]

    # A condition that expires with the combat row has no consequential clearing roll.
    if not wrap.combat_ended:
        for event in wrap.tick_conditions_due[cursor["index"] :]:
            actor = state.get_participant(event["actor_id"])
            assert actor is not None
            result = await fate_rolls.save(
                session,
                cursor,
                actor.id,
                event["type"],
                partial(_roll_tick_save, state, actor, event, save_resolver),
                queries=queries,
                conn=conn,
            )
            if result is None:
                state.wrap_continuation = cursor
                state.beat = combat_phase.PhaseBeat.NARRATION
                return state, None, combat_phase.PhaseAdvance(beat_completed=state.beat), {}, None, None, {}
            if result.success:
                actor.conditions = conditions.remove_condition(actor.conditions, event["type"])
            cursor["index"] += 1
        state.beat = combat_phase.PhaseBeat.DECLARATION
        combat_phase._reset_legendary_actions(state)
    state.wrap_continuation = None
    wrap_adv = combat_phase.PhaseAdvance(
        beat_completed=combat_phase.PhaseBeat.WRAP,
        wrap=wrap,
        legendary_available=[] if wrap.combat_ended else combat_phase._boss_legendaries(state),
    )

    pending_by_member = combat_hollow_resonance.take_totals(state)

    ended_outcome = wrap.outcome if (wrap is not None and wrap.combat_ended and wrap.outcome) else None
    if ended_outcome is None:
        await concealment.expire_gift(state, conn=conn, queries=queries)
        combat_recharge.recharge_round(state)
        from still_illusions import generate

        generate(state)
        # Combat continues: shed one step of Resonance per phase, per member against their OWN
        # pool (M14 story-004) — never a shared value, never double. WRAP is the canonical combat
        # decay clock (decision resonance-decay-phase-canonical) — cast-paced decay is suppressed
        # in combat (spell_casting), so this never double-decays. Each member's decay base is its
        # ability-generated total when it cast this phase (pending_by_member), else its standing
        # value. Persist only when the value actually moved (a 0 floor stays silent); the in-memory
        # sync + HUD push happen post-commit so a rolled-back phase shows no decay.
        if wrap is not None and wrap.resonance_decay:
            for m in session.party.members:
                base = pending_by_member.get(m.player_id, m.resonance.current)
                decayed = max(0, base - wrap.resonance_decay)
                if decayed != base:
                    pending_by_member[m.player_id] = decayed
                    await resonance_mutations.update_player_resonance(m.player_id, decayed, conn=conn)
        await mutations.save_combat_state(state.combat_id, state.to_dict(), conn=conn)
        # Push the HUD's combat-tracker + condition icons live (M12 story-001). Built from the
        # post-tick state (save-cleared conditions are gone) and buffered in the sink so the
        # packet only reaches the client AFTER the phase tx commits — a rolled-back phase
        # leaves the captured event discarded along with `state`. Skipped on the terminal wrap
        # (the `else` branch below) because COMBAT_ENDED clears the mobile combat state.
        await emit_or_publish(
            sink,
            session.room,
            E.COMBAT_UI_UPDATE,
            build_combat_ui_update(state),
            event_bus=session.event_bus,
        )
    else:
        # Combat ended: end_combat's DB writes (durability accrual + combat-row delete) join the
        # WRAP COMMIT, so a mid-end failure rolls that commit back atomically. Under the two-commit
        # split (M29, story-016) the ally results from commit 1 stand — they are durable and the
        # enemy actions are persisted as pending, a legal resting state rather than a torn one.
        # Its COMBAT_ENDED + stinger buffer into the shared sink; the in-memory teardown + handoff
        # run post-commit via _end_combat_finish below.
        end_data = await _end_combat_db(
            session, state, ended_outcome, mutations=mutations, queries=queries, conn=conn, sink=sink
        )
    return state, wrap, wrap_adv, exhaustion_narration, ended_outcome, end_data, pending_by_member
