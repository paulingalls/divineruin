"""Combat phase-loop tools — declare_phase, resolve_phase — orchestrating the per-phase
transaction and the initiative-ordered packet loop (M4.1, story-003). The per-packet resolvers
live in combat_support (_resolve_attack_packet) and combat_ability (_resolve_ability_packet)
(story-007 split, to keep this file under the 500-line ceiling). request_death_save lives in combat_death_save.py (story-004
split, debt faa6dd19ab64)."""

import json
import logging

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import check_resolution_attack
import check_resolution_save
import combat_phase
import concentration_break
import db
import db_mutations
import db_mutations_resonance
import db_queries
import event_types as E
import fatigue_narration
import resonance_events
import spell_casting
import veil_ward_events
import ward_resolution
from combat_ability import AbilityCastOutcome
from combat_end import POST_COMMIT_PUBLISH_FAILED, _end_combat_db, _end_combat_finish
from combat_events import EventSink, emit_or_publish, scratch_guard
from combat_packet import _prevalidate_ability_focus, _resolve_one_packet, _resolve_tick_saves
from combat_support import _require_combat
from combat_ui_update import build_combat_ui_update
from db_errors import db_tool
from declarations import DeclarationType
from session_data import SessionData

logger = logging.getLogger("divineruin.tools")


@function_tool()
@db_tool
async def declare_phase(
    context: RunContext[SessionData],
    declarations: dict[str, dict],
) -> str:
    """Open a combat phase by recording every combatant's declared action for this
    round, then call resolve_phase to resolve them. Pass a mapping of participant ID
    to that combatant's declaration, e.g.
    {"player_1": {"action": "Longsword", "target_id": "goblin_1"},
     "goblin_1": {"action": "Scimitar", "target_id": "player_1"}}.
    Include the player, every conscious companion, and every enemy that acts this
    phase. Call this once per round at the declaration beat; resolve_phase resolves
    and narrates the whole phase in initiative order."""
    return await _declare_phase_impl(context, declarations)


async def _declare_phase_impl(
    context: RunContext[SessionData],
    declarations: dict[str, dict],
    *,
    mutations=db_mutations,
) -> str:
    logger.info("declare_phase called: %d declarations", len(declarations or {}))
    session: SessionData = context.userdata

    cs = _require_combat(session)
    if cs.beat != combat_phase.PhaseBeat.DECLARATION:
        raise ToolError(f"Not at the declaration beat (current beat: {cs.beat}). Call resolve_phase first.")

    # The pure engine records the declarations and advances DECLARATION -> RESOLUTION.
    # An empty declarations payload is a ValueError from the engine — surface it as a
    # ToolError so the DM re-prompts rather than crashing combat.
    try:
        next_state, _adv = combat_phase.advance_combat_phase(cs, declarations=declarations)
    except ValueError as e:
        raise ToolError(str(e)) from e

    session.combat_state = next_state
    await mutations.save_combat_state(next_state.combat_id, next_state.to_dict())

    response = {
        "beat": next_state.beat,
        "round": next_state.round_number,
        "accepted_actors": list(next_state.pending_declarations.keys()),
    }
    logger.info("declare_phase result: beat=%s, actors=%s", next_state.beat, response["accepted_actors"])
    return json.dumps(response)


@function_tool()
@db_tool
async def resolve_phase(
    context: RunContext[SessionData],
) -> str | tuple:
    """Resolve the combat phase declared by declare_phase. Drives the deterministic
    engine: resolves every declared attack in initiative order against the
    combatants' HP, narrates the outcomes (you supply the prose from the returned
    packets), then wraps the phase — Resonance decays, death saves come due, and if
    every enemy has fallen (or the player has died) combat ends and hands back to the
    exploration agent. Call this once, right after declare_phase. The response lists
    per-actor resolution packets to narrate plus any death saves the player owes.
    The ``exhaustion_narration`` map (participant ID -> flavor line) gives the
    weariness cue to weave into the narration for any actor carrying Exhausted stacks."""
    return await _resolve_phase_impl(context)


async def _resolve_phase_impl(
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
) -> str | tuple:
    logger.info("resolve_phase called")
    session: SessionData = context.userdata

    cs = _require_combat(session)
    if cs.beat != combat_phase.PhaseBeat.RESOLUTION:
        raise ToolError(f"Not at the resolution beat (current beat: {cs.beat}). Call declare_phase first.")

    # One transaction spans every DB write of the phase — per-packet HP + durability, the per-phase
    # Resonance decay, the trailing save_combat_state, and (on the end-condition) end_combat's
    # durability + combat-row delete — so a mid-phase failure rolls back atomically and players/items
    # can never diverge from the combat_instances JSONB SSOT (debt 084c7d0bc457, concern 7198554c2d4c).
    # The in-memory Resonance sync + HUD publish run AFTER commit (below). pending_by_member holds
    # each member's post-cast/decay Resonance total for THIS phase, keyed by player_id (M14 story-004)
    # — the WRAP decays each member against their OWN pool, never a shared value.
    pending_by_member: dict[str, int] = {}
    end_data: dict | None = None
    # The ward the party entered this phase under. The WRAP beat's round clock can retire a ROUNDS
    # ward mid-fight (combat_phase._wrap), and that clearing is silent — the engine is pure, it emits
    # nothing. Captured pre-tx so a rollback (which restores `cs`) can never make a surviving ward
    # look expired. The post-commit publish below is what darkens the client's ward indicator.
    ward_before = cs.veil_ward
    # Buffer every client event the phase emits; flush only AFTER the tx commits so a rolled-back
    # phase never leaks a phantom DICE_ROLL/ITEM_DURABILITY_HIT/sound (concern 03f2907d9c93). The
    # scratch_guard snapshots the in-loop session scratch (weapon flags, companion KO, recent_events)
    # and restores it if the tx rolls back, so no in-memory state sticks through a failed phase (AC3).
    sink = EventSink()
    async with scratch_guard(session), db_mod.transaction() as conn:
        # Beat 2 (resolution): the engine orders the pending declarations into initiative
        # packets (no math of its own). Orchestration applies each attack against
        # CombatParticipant HP via the shared packet resolver. A malformed/old-shape
        # stored declaration (e.g. a combat persisted before the explicit-type change)
        # raises ValueError here as resolve_declaration re-validates; translate it to
        # ToolError like declare_phase does so the DM re-prompts instead of crashing.
        try:
            state, adv = combat_phase.advance_combat_phase(cs)
        except ValueError as e:
            raise ToolError(str(e)) from e

        # Defend pre-pass: a Defend declaration grants +AC for the WHOLE phase regardless of
        # initiative order, so apply every Defend's bonus to state.ac_modifiers before any
        # attack packet resolves (otherwise a higher-initiative attacker would bypass it).
        # A fallen defender grants no bonus — mirror the per-packet "actor unavailable" guard.
        for packet in adv.packets:
            if packet.declaration.type is not DeclarationType.DEFEND or not packet.declaration.ac_bonus:
                continue
            defender = state.get_participant(packet.actor_id)
            if defender is not None and not defender.is_fallen:
                state.ac_modifiers[packet.actor_id] = packet.declaration.ac_bonus

        # Pre-validate Focus for every player ABILITY BEFORE resolving anything (AC2): an unaffordable
        # in-combat ability fails loud (ToolError) with no writes — and before any other actor's HP
        # write, so it never rolls back a phase that already resolved attacks. Returns the for_update
        # player row (the cast reuses it; the lock is taken once) or None when no player ability.
        players_by_id = await _prevalidate_ability_focus(
            session, state, adv, conn=conn, queries=queries, cast_resolver=cast_resolver
        )

        # Each declaring member's ABILITY CastResult lands here (keyed by player_id) for the
        # post-commit apply (per-member resonance seed, concentration sync, deferred events). Stays
        # empty when no ability was declared.
        cast_outcome = AbilityCastOutcome()
        packet_summaries: list[dict] = []
        for packet in adv.packets:
            packet_summaries.append(
                await _resolve_one_packet(
                    session,
                    state,
                    packet,
                    mutations=mutations,
                    queries=queries,
                    resolver=resolver,
                    concentration_break_mod=concentration_break_mod,
                    conn=conn,
                    sink=sink,
                    cast_resolver=cast_resolver,
                    cast_outcome=cast_outcome,
                    players_by_id=players_by_id,
                )
            )

        # Beat 3 (narration) is an engine no-op; Beat 4 (wrap) computes the end-condition,
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
            # Combat ended: end_combat's DB writes (durability accrual + combat-row delete) join THIS
            # transaction so a mid-end failure rolls the phase back atomically (concern 7198554c2d4c).
            # Its COMBAT_ENDED + stinger buffer into the shared sink; the in-memory teardown + handoff
            # run post-commit via _end_combat_finish below.
            end_data = await _end_combat_db(
                session, state, ended_outcome, mutations=mutations, queries=queries, conn=conn, sink=sink
            )

    # Sync the looped in-memory state ONLY after the transaction commits, and do it FIRST — before
    # any fallible publish (story-010). On rollback the exception skips all of this, so
    # session.combat_state stays the pristine pre-phase `cs` — consistent with the rolled-back DB
    # SSOT — and a retried turn proceeds from committed HP (engine deep-copies, so `cs` was never
    # mutated). On the ENDING wrap the commit is what made the party's XP/loot/coin durable, so the
    # guard against a second end (session.combat_state, which _require_combat reads) has to be
    # released with it: _end_combat_finish runs here rather than after the publishes, else a publish
    # failure would leave the party paid, the combat row deleted, and the guard still armed — and
    # the DM's recovery end_combat("victory") would pay the whole party AGAIN. Everything in this
    # block is pure in-memory (no awaits, no DB, no events), so it cannot fail partway.
    #
    # The ward publish below resolves the LOCATION scope, and _end_combat_finish moves
    # session.location_id to the death anchor on a primary-death end — so capture the location the
    # party fought at now and pass it explicitly, rather than let the ward answer depend on teardown
    # ordering.
    ward_location_id = session.location_id
    handoff: tuple | None = None
    if ended_outcome is None:
        session.combat_state = state
    else:
        assert end_data is not None  # set in the tx whenever ended_outcome is not None
        handoff = _end_combat_finish(session, state, ended_outcome, end_data)
    # The per-phase Resonance change per member (M14 story-004): the in-memory half of the sync,
    # infallible like the rest of this block. Only members that actually moved this phase (in
    # pending_by_member) sync; the client push for each is in the publish region below.
    for m in session.party.members:
        if m.player_id in pending_by_member:
            m.resonance.current = pending_by_member[m.player_id]

    # Post-commit publishes. A failure here is LOGGED, not raised (story-010, decision 788d61b73623):
    # see combat_end.POST_COMMIT_PUBLISH_FAILED for the policy — the committed transaction is
    # authoritative, the HUD is a mirror, and a mirror that fails to update must not strand a session
    # whose rewards are already banked. On the ending wrap that is literal: this function's return is
    # the ONLY exit from CombatAgent, so a raise here would leave the party stuck in combat forever.
    try:
        # Release the buffered loop events to the client.
        await sink.flush()

        # The WRAP retired a ROUNDS ward this phase: darken the client's ward indicator. Without this
        # the mechanic and the HUD diverge — casts stop being halved while the player still sees a
        # ward, so they walk into an Overreach believing they are protected. The encounter scope is
        # empty either way here (state.veil_ward is None is this branch's own condition), so the
        # resolver falls through to whatever location ward still covers the party — a Sacred Site
        # keeps the light on. This never double-emits with _end_combat_db's own ward event: that one
        # fires only when the ward SURVIVED to the ending wrap (`cs.veil_ward is not None`), which is
        # the exact complement of the condition here.
        if ward_before is not None and state.veil_ward is None:
            expired_ward, expired_scope = await ward_resolution.resolve_scope_ward_with_scope(
                session, conn=await db_mod.get_pool(), location_id=ward_location_id
            )
            await veil_ward_events.publish_veil_ward_changed(session, expired_ward, expired_scope)

        # Apply each in-combat ability's deferred effects: flush every caster's own deferred client
        # events (hollow echo, Vaelti warning). Concentration is synced IN-LOOP by
        # _resolve_ability_packet (not here) so a same-phase, lower-initiative concentration break
        # sees the just-cast spell (story-007). Runs even on the ending wrap so an ability that fires
        # on the killing phase still applies its effects.
        for cr in cast_outcome.results.values():
            await cr.flush_events()

        # Push each moved member's Resonance: an ability can generate Resonance on the same phase it
        # drops the last enemy, and that qualitative HUD state must still reach the client even though
        # combat ends. Each ability suppressed its own RESONANCE_CHANGED, so this is the single
        # authoritative push per member per phase — under the member's OWN resonance_track +
        # caster_id so the client filters it to the right player.
        for m in session.party.members:
            if m.player_id in pending_by_member:
                await resonance_events_mod.publish_resonance_changed(
                    session, resonance_track=m.resonance, caster_id=m.player_id
                )
    except Exception:
        logger.exception(POST_COMMIT_PUBLISH_FAILED, "resolve_phase")

    # Beat 4 end-condition: the engine reported victory (all enemies fallen) or defeat (the player
    # has died). end_combat's DB writes committed inside the phase tx and its in-memory teardown ran
    # above; hand the party back to the exploration agent.
    if handoff is not None:
        logger.info("resolve_phase: engine end-condition %s -> end_combat", ended_outcome)
        return handoff

    response = {
        "beat": state.beat,
        "round": state.round_number,
        "packets": packet_summaries,
        "death_saves_due": wrap.death_saves_due if wrap else [],
        "exhaustion_narration": exhaustion_narration,
        # Boss legendary actions available for the round just entered (M4.7, story-009): the engine
        # reset each living Boss's 1/round budget at this WRAP and surfaced it on wrap_adv. Surface it
        # to the DM so the Boss's extra beat is narratable; the DM spends it via consume_legendary_action.
        "legendary_available": wrap_adv.legendary_available,
    }
    logger.info(
        "resolve_phase result: beat=%s, round=%d, packets=%d", state.beat, state.round_number, len(packet_summaries)
    )
    return json.dumps(response)


@function_tool()
@db_tool
async def consume_legendary_action(
    context: RunContext[SessionData],
    boss_id: str,
) -> str:
    """Spend one of a Boss's legendary actions to give it an extra beat this round. Call this when
    resolve_phase's ``legendary_available`` lists a Boss and you want it to act again outside its
    initiative turn — then narrate that extra action and resolve it through the normal declare/resolve
    or cast tools. A Boss has ONE legendary action per round (refreshed at the next wrap); calling
    this when the budget is spent, or on a non-Boss, is rejected. Pass the Boss's participant id."""
    return await _consume_legendary_action_impl(context, boss_id)


async def _consume_legendary_action_impl(
    context: RunContext[SessionData],
    boss_id: str,
    *,
    mutations=db_mutations,
) -> str:
    session: SessionData = context.userdata
    cs = _require_combat(session)
    # The pure engine owns the 1/round rule + fail-loud (unknown / not-a-Boss / exhausted); surface
    # those as a ToolError so the DM re-prompts instead of crashing the turn.
    try:
        next_state = combat_phase.consume_legendary_action(cs, boss_id)
    except ValueError as e:
        raise ToolError(str(e)) from e
    session.combat_state = next_state
    await mutations.save_combat_state(next_state.combat_id, next_state.to_dict())
    boss = next_state.get_participant(boss_id)
    remaining = boss.legendary_actions if boss is not None else 0
    logger.info("consume_legendary_action: %s spent a legendary action (%d remaining)", boss_id, remaining)
    return json.dumps({"actor_id": boss_id, "legendary_actions_remaining": remaining})
