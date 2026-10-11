"""Resolve-phase transactions and post-commit session updates."""

import copy
import json
import logging
from typing import Any

from livekit.agents.llm import ToolError
from livekit.agents.voice import RunContext

import character_spells
import check_resolution_attack
import check_resolution_save
import choir_encounter
import combat_hold
import combat_hollow_resonance
import combat_phase
import combat_spatial
import combat_spatial_declarations
import combat_wrap
import concentration_break
import db
import db_mutations
import db_mutations_resonance
import db_queries
import event_types as E
import resonance_events
import spell_casting
import veil_ward_events
import ward_resolution
from combat_ability import AbilityCastOutcome
from combat_end import _end_combat_finish
from combat_events import EventSink, emit_or_publish, isolated_publish
from combat_packet import _prevalidate_ability_focus, _resolve_one_packet
from combat_phase_recovery import PrevalidationRefusal, phase_transaction_with_recovery
from combat_support import _participant_roster, _require_combat
from combat_ui_update import build_combat_ui_update
from declarations import DeclarationType
from session_data import SessionData

logger = logging.getLogger("divineruin.tools")


async def _resolve_phase_locked(
    context: RunContext[SessionData],
    *,
    mutations=db_mutations,
    queries=db_queries,
    resolver=check_resolution_attack,
    save_resolver=check_resolution_save,
    concentration_break_mod=concentration_break,
    resonance_mutations=db_mutations_resonance,
    resonance_events_mod=resonance_events,
    db_mod=db,
    cast_resolver=spell_casting,
    character_spells_mod=character_spells,
) -> str | tuple:
    logger.info("resolve_phase called")
    session: SessionData = context.userdata

    cs = _require_combat(session)
    if cs.beat not in (combat_phase.PhaseBeat.RESOLUTION, combat_phase.PhaseBeat.NARRATION):
        raise ToolError(f"Not at the resolution or narration beat (current beat: {cs.beat}). Call declare_phase first.")
    try:
        combat_spatial_declarations.preflight_state(cs)
    except ValueError as error:
        raise ToolError(str(error)) from error
    resolving_allies = cs.beat == combat_phase.PhaseBeat.RESOLUTION

    # Ally results commit before held actions; only the drained held pass wraps the phase.
    pending_by_member: dict[str, int] = {}
    end_data: dict | None = None
    # Capture before recovery can restore state, so rollback cannot imply ward expiry.
    ward_before = cs.veil_ward
    # Client events must remain buffered until the transaction commits.
    sink = EventSink()
    packet_deps: dict[str, Any] = {
        "mutations": mutations,
        "queries": queries,
        "resolver": resolver,
        "concentration_break_mod": concentration_break_mod,
        "cast_resolver": cast_resolver,
    }
    cast_outcome = AbilityCastOutcome()
    packet_summaries: list[dict] = []
    async with phase_transaction_with_recovery(session, cs, db_mod=db_mod, mutations=mutations) as conn:
        if resolving_allies:
            # Reopen declaration on malformed persisted actions instead of retrying them forever.
            try:
                state, adv = combat_phase.advance_combat_phase(cs)
                combat_spatial_declarations.preflight(state, [(p.actor_id, p.declaration) for p in adv.packets])
            except ValueError as e:
                raise PrevalidationRefusal(ToolError(str(e))) from e

            # Defend protects the whole phase, including attacks earlier in initiative.
            for packet in adv.packets:
                if packet.declaration.type is not DeclarationType.DEFEND or not packet.declaration.ac_bonus:
                    continue
                defender = state.get_participant(packet.actor_id)
                if defender is not None and not defender.is_fallen:
                    state.ac_modifiers[packet.actor_id] = packet.declaration.ac_bonus

            # Refuse unaffordable abilities before any actor writes HP; recovery reopens declaration.
            try:
                players_by_id = await _prevalidate_ability_focus(
                    session,
                    state,
                    adv,
                    conn=conn,
                    queries=queries,
                    cast_resolver=cast_resolver,
                    character_spells_mod=character_spells_mod,
                )
            except ToolError as error:
                raise PrevalidationRefusal(error) from error

            ally_packets, enemy_packets = combat_phase.partition_packets(state, adv.packets)
            from combat_turn_start import ally_turns, turn_start

            for actor, packet in ally_turns(state, ally_packets):
                if actor is not None:
                    summary = await turn_start(session, state, actor, conn=conn, sink=sink, **packet_deps)
                    if summary is not None:
                        packet_summaries.append(summary)
                if packet is None:
                    continue
                if actor is not None and not actor.is_ally:
                    packet_summaries.append({"actor_id": actor.id, "resolved": False, "reason": "actor became hostile"})
                    continue
                packet_summaries.append(
                    await _resolve_one_packet(
                        session,
                        state,
                        packet,
                        **packet_deps,
                        conn=conn,
                        sink=sink,
                        cast_outcome=cast_outcome,
                        players_by_id=players_by_id,
                    )
                )
            state.held_actions = combat_hold.hold_enemy_packets(state, enemy_packets)
        else:
            state = copy.deepcopy(cs)
            packet_summaries = await combat_hold.pump(
                session, state, packet_deps={**packet_deps, "conn": conn, "sink": sink, "cast_outcome": cast_outcome}
            )

        if resolving_allies or state.open_window is not None:
            exhaustion_narration: dict[str, str] = {}
            wrap = None
            wrap_adv = combat_phase.PhaseAdvance(beat_completed=combat_phase.PhaseBeat.NARRATION)
            ended_outcome = None
            pending_by_member = combat_hollow_resonance.take_totals(state)
            await emit_or_publish(
                sink,
                session.room,
                E.COMBAT_UI_UPDATE,
                build_combat_ui_update(state),
                event_bus=session.event_bus,
            )
            await mutations.save_combat_state(state.combat_id, state.to_dict(), conn=conn)
        else:
            (
                state,
                wrap,
                wrap_adv,
                exhaustion_narration,
                ended_outcome,
                end_data,
                pending_by_member,
            ) = await combat_wrap.wrap_phase(
                session,
                state,
                conn=conn,
                sink=sink,
                cast_outcome=cast_outcome,
                mutations=mutations,
                queries=queries,
                save_resolver=save_resolver,
                resonance_mutations=resonance_mutations,
            )

    # Sync and tear down before fallible publishes, preventing a second reward payout.
    # Capture the combat location before teardown can move the party to its death anchor.
    ward_location_id = session.location_id
    handoff: tuple | None = None
    if ended_outcome is None:
        session.combat_state = state
    else:
        assert end_data is not None
        handoff = _end_combat_finish(session, state, ended_outcome, end_data)
    for m in session.party.members:
        if m.player_id in pending_by_member:
            m.resonance.current = pending_by_member[m.player_id]

    # Isolate each publish: a failed mirror must not block handoff or another member's update.
    with isolated_publish("resolve_phase sink flush"):
        await sink.flush()

    with isolated_publish("resolve_phase ward push"):
        # Ending-combat ward publication covers surviving wards; this covers expired wards.
        if ward_before is not None and state.veil_ward is None:
            expired_ward, expired_scope = await ward_resolution.resolve_scope_ward_with_scope(
                session, conn=await db_mod.get_pool(), location_id=ward_location_id
            )
            await veil_ward_events.publish_veil_ward_changed(session, expired_ward, expired_scope)

    for caster_id, cr in cast_outcome.results.items():
        with isolated_publish(f"resolve_phase deferred cast events ({caster_id})"):
            await cr.flush_events()

    for m in session.party.members:
        if m.player_id in pending_by_member:
            with isolated_publish(f"resolve_phase resonance push ({m.player_id})"):
                await resonance_events_mod.publish_resonance_changed(
                    session, resonance_track=m.resonance, caster_id=m.player_id
                )

    if handoff is not None:
        logger.info("resolve_phase: engine end-condition %s -> end_combat", ended_outcome)
        return handoff

    response = {
        "choir": choir_encounter.facts(state),
        "spatial": combat_spatial.response_facts(state, session.acting_player_id, session.primary_player_id),
        "beat": state.beat,
        "round": state.round_number,
        "packets": packet_summaries,
        "participants": _participant_roster(state.participants),
        "next": combat_wrap.next_envelope(state),
        "death_saves_due": wrap.death_saves_due if wrap else [],
        "exhaustion_narration": exhaustion_narration,
        "legendary_available": wrap_adv.legendary_available,
    }
    logger.info(
        "resolve_phase result: beat=%s, round=%d, packets=%d", state.beat, state.round_number, len(packet_summaries)
    )
    return json.dumps(response)
