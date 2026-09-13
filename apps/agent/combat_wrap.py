"""Beat 4 — the phase wrap, and the ``next`` envelope the DM reads (M29, story-016).

Split out of combat_turn.py, which took the two-commit Beat-3 hold and the 500-line ceiling in the
same change. Both pieces belong to the END of a round rather than to its orchestration:
``_wrap_phase`` runs exactly once per round, in the LAST commit, and ``next_envelope`` says what
the DM does after whichever commit just landed.
"""

import combat_phase
import event_types as E
import fatigue_narration
from combat_ability import _find_action
from combat_end import _end_combat_db
from combat_events import emit_or_publish
from combat_packet import _resolve_tick_saves
from combat_ui_update import build_combat_ui_update
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

    This is the window PRODUCER (constraint 6). Sprint 45 shipped a gate keyed on a reaction
    ``window`` the DM had to guess among nine members of abilities.REACTION_WINDOWS; here the
    engine names the window it is paused on, and the DM passes back an id it minted.

    ``verbs`` is the ADVANCE set, not a whitelist of everything legal right now, and the prompt
    says so: the same result payload carries ``death_saves_due`` and ``legendary_available``, whose
    verbs (request_death_save, consume_legendary_action) have no beat gate and are still owed at
    the very moment ``verbs`` reads ``["declare_phase"]``. Reading it as exhaustive would have the
    DM skip a downed player's death save — so it names the move that steps the machine, and
    nothing more.

    ``activate`` IS legal at an open window since story-017 — validate_reaction_activation gates
    on this very ``open_window`` — and it is still deliberately ABSENT from ``verbs``, because
    ``verbs`` names the ADVANCE move and only resolve_phase advances a paused beat. The producer
    for activation is the prompt plus ``waiting_on.triggers``, which name the windows the DM's
    reaction must match (constraint 6); listing a non-advancing verb here would contradict the
    "not a whitelist" reading in the same payload.
    """
    if state.open_window is not None:
        window = state.open_window
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
            },
        }
    if state.beat == combat_phase.PhaseBeat.NARRATION:
        return {"phase": "narration", "verbs": ["resolve_phase"], "waiting_on": None}
    return {"phase": "declaration", "verbs": ["declare_phase"], "waiting_on": None}


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
) -> tuple:
    """Beat 3 -> Beat 4, in the LAST commit of the phase (M29, story-016).

    Runs exactly once per round, when the held enemy queue has drained — never on a pause commit
    and never in both. It rides the last commit rather than the first because an enemy blow can be
    what ends the fight, so the end-condition cannot be computed before the enemies have acted.

    Returns ``(state, wrap, wrap_adv, exhaustion_narration, ended_outcome, end_data,
    pending_by_member)``. The Resonance map is BUILT here rather than taken as a parameter: the
    caller's copy is only ever populated on the pause branch, which is the branch that does not
    reach this function, so accepting one would have been a value this function always discarded.
    It comes back because the post-commit in-memory sync reads it.
    """
    end_data: dict | None = None
    # Beat 3 (narration) is done; Beat 4 (wrap) computes the end-condition,
    # death saves due, and the per-phase Resonance decay signal.
    state, _narr = combat_phase.advance_combat_phase(state)
    # Beat-3 display layer (M4.3, story-005): surface exhaustion flavor for every participant
    # carrying Exhausted stacks so the DM speaks it. Read here (pre-wrap, pre-tick) so a
    # save-to-clear tick below never erases a participant's narration mid-beat.
    exhaustion_narration = {
        p.id: narrative
        for p in state.participants
        if (narrative := fatigue_narration.exhaustion_narrative_for_conditions(p.conditions))
    }
    state, wrap_adv = combat_phase.advance_combat_phase(state)
    wrap = wrap_adv.wrap

    # Beat-4 save-to-clear (M4.3, story-004): resolve the saves the wrap surfaced (Frightened's
    # WIS save). A made save clears the condition on the actor in-memory; the change rides the
    # save_combat_state / end-combat write below in this same tx.
    if wrap is not None and wrap.tick_conditions_due:
        _resolve_tick_saves(state, wrap.tick_conditions_due, save_resolver)

    # Each in-combat ability GENERATES Resonance during resolution (beat 2); seed each caster's
    # pending value with the cast's post-generation total so the WRAP decay below sheds from it
    # (net = standing + generated - decay), not the stale standing value. new_resonance is None
    # for a cantrip/floored cast (no write) — that member is omitted, leaving its standing value
    # as the decay base.
    pending_by_member = {
        mid: cr.new_resonance for mid, cr in cast_outcome.results.items() if cr.new_resonance is not None
    }

    ended_outcome = wrap.outcome if (wrap is not None and wrap.combat_ended and wrap.outcome) else None
    if ended_outcome is None:
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
