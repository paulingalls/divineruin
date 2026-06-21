"""Combat phase-loop tools — declare_phase, resolve_phase — orchestrating the per-phase
transaction and the initiative-ordered packet loop (M4.1, story-003). The per-packet resolvers
live in combat_support (_resolve_attack_packet) and combat_ability (_resolve_ability_packet)
(story-007 split, to keep this file under the 500-line ceiling). request_death_save lives in combat_death_save.py (story-004
split, debt faa6dd19ab64)."""

import json
import logging

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import check_resolution
import check_resolution_attack
import check_resolution_save
import combat_enhancers
import combat_phase
import combat_resolution
import concentration_break
import conditions
import db
import db_mutations
import db_mutations_resonance
import db_queries
import fatigue_narration
import resonance_events
import spell_casting
from combat_ability import (
    AbilityCastOutcome,
    _attach_riders,
    _find_action,
    _resolve_ability_packet,
)
from combat_end import _end_combat_db, _end_combat_finish
from combat_events import EventSink, scratch_guard
from combat_support import _require_combat, _resolve_attack_packet
from db_errors import db_tool
from declarations import DeclarationType
from session_data import SessionData

logger = logging.getLogger("divineruin.tools")

# Beat-4 save-to-clear DC (M4.3, story-004): the spec's end-of-turn condition saves (Frightened's
# WIS save) have no per-condition DC, so use a fixed moderate DC. A seam: a future per-condition DC
# would replace this constant (assumption f760751a1109).
_CONDITION_CLEAR_DC = 10


def _resolve_tick_saves(state, tick_conditions_due, save_resolver):
    """Resolve the Beat-4 save-to-clear conditions the wrap surfaced (M4.3, story-004).

    For each {actor_id, type, save, source}, roll the actor's save against the clear DC; on a SUCCESS
    remove that condition from the actor (it clears), on a failure it persists. Pure in-memory: the
    removal rides the phase's existing save_combat_state / end-combat write — no extra persist here,
    no client event (narration-only). The engine never rolls; this is where the roll happens.
    """
    for event in tick_conditions_due:
        actor = state.get_participant(event["actor_id"])
        if actor is None:
            continue
        player_data = {"attributes": actor.attributes, "level": actor.level, "conditions": actor.conditions}
        # The catalog's tick_save is the 3-letter abbreviation ("wis"); resolve_saving_throw
        # validates against the full attribute name ("wisdom"), so expand before resolving.
        save_type = check_resolution._ATTR_FULL.get(event["save"], event["save"])
        result = save_resolver.resolve_saving_throw(player_data, save_type, _CONDITION_CLEAR_DC, event["type"])
        if result.success:
            actor.conditions = conditions.remove_condition(actor.conditions, event["type"])


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
    # The in-memory Resonance sync + HUD publish run AFTER commit (below).
    pending_resonance: int | None = None
    end_data: dict | None = None
    cast_result = None  # spell_casting.CastResult when a player ABILITY resolved this phase
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
        player = await _prevalidate_ability_focus(
            session, state, adv, conn=conn, queries=queries, cast_resolver=cast_resolver
        )

        # At most one player ABILITY resolves per phase (one declaration per participant); its
        # CastResult lands here for the post-commit apply (resonance seed, concentration sync,
        # deferred events). Stays empty when no ability was declared.
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
                    player=player,
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

        # An in-combat ability GENERATES Resonance during resolution (beat 2); seed the phase's
        # pending value with the cast's post-generation total so the WRAP decay below sheds from it
        # (net = standing + generated - decay), not the stale standing value. new_resonance is None
        # for a cantrip/floored cast (no write), leaving the standing value as the decay base.
        cast_result = cast_outcome.cast_result
        if cast_result is not None and cast_result.new_resonance is not None:
            pending_resonance = cast_result.new_resonance

        ended_outcome = wrap.outcome if (wrap is not None and wrap.combat_ended and wrap.outcome) else None
        if ended_outcome is None:
            # Combat continues: shed one step of Resonance per phase. WRAP is the canonical combat
            # decay clock (decision resonance-decay-phase-canonical) — cast-paced decay is suppressed
            # in combat (spell_casting), so this never double-decays. The decay base is the ability's
            # generated total when one cast this phase (pending_resonance), else the standing value.
            # Persist only when the value actually moved (a 0 floor stays silent); the in-memory sync
            # + HUD push happen post-commit so a rolled-back phase shows no decay.
            if wrap is not None and wrap.resonance_decay:
                decay_base = pending_resonance if pending_resonance is not None else session.resonance.current
                decayed = max(0, decay_base - wrap.resonance_decay)
                if decayed != decay_base:
                    pending_resonance = decayed
                    await resonance_mutations.update_player_resonance(session.player_id, decayed, conn=conn)
            await mutations.save_combat_state(state.combat_id, state.to_dict(), conn=conn)
        else:
            # Combat ended: end_combat's DB writes (durability accrual + combat-row delete) join THIS
            # transaction so a mid-end failure rolls the phase back atomically (concern 7198554c2d4c).
            # Its COMBAT_ENDED + stinger buffer into the shared sink; the in-memory teardown + handoff
            # run post-commit via _end_combat_finish below.
            end_data = await _end_combat_db(
                session, state, ended_outcome, mutations=mutations, queries=queries, conn=conn, sink=sink
            )

    # Sync the looped in-memory state ONLY after the transaction commits. On rollback the
    # exception skips this line, so session.combat_state stays the pristine pre-phase `cs` —
    # consistent with the rolled-back DB SSOT — and a retried turn proceeds from committed HP
    # (engine deep-copies, so `cs` was never mutated).
    session.combat_state = state

    # The tx committed: now (and only now) release the buffered loop events to the client.
    await sink.flush()

    # Apply the in-combat ability's deferred effects post-commit (rollback-safe — a rolled-back tx
    # skipped to here via the re-raise): flush the cast's own deferred client events (hollow echo,
    # Vaelti warning). Concentration is synced IN-LOOP by _resolve_ability_packet (not here) so a
    # same-phase, lower-initiative concentration break sees the just-cast spell (story-007). The
    # generated Resonance is synced just below (shared with the decay path). Runs BEFORE the
    # end-of-combat return so an ability that fires on the killing phase still applies its effects.
    if cast_result is not None:
        await cast_result.flush_events()
    # Sync + push the per-phase Resonance change BEFORE the end-of-combat return: an ability can
    # generate Resonance on the same phase it drops the last enemy, and that qualitative HUD state
    # must still reach the client even though combat ends. The ability suppressed its own
    # RESONANCE_CHANGED, so this is the single authoritative push per phase. (Pre-story-007 this was
    # a no-op on the terminal wrap — only the WRAP-decay branch set pending_resonance, and that
    # branch never runs when combat ends; now an in-loop ability sets it regardless of end state.)
    if pending_resonance is not None:
        session.resonance.current = pending_resonance
        await resonance_events_mod.publish_resonance_changed(session)

    # Beat 4 end-condition: the engine reports victory (all enemies fallen) or defeat (the player
    # has died). end_combat's DB writes already committed inside the phase tx above; now apply its
    # in-memory teardown (clear combat_state, reset encounter flags) and return the handoff.
    if ended_outcome is not None:
        logger.info("resolve_phase: engine end-condition %s -> end_combat", ended_outcome)
        assert end_data is not None  # set in the tx whenever ended_outcome is not None
        return _end_combat_finish(session, state, ended_outcome, end_data)

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


async def _prevalidate_ability_focus(session, state, adv, *, conn, queries, cast_resolver):
    """Pre-validate every player ABILITY declaration's Focus BEFORE the resolution loop (AC2).

    An unaffordable in-combat ability must fail loud (ToolError) with NO state writes — and crucially
    before any OTHER actor's HP/durability write, so a bad ability never rolls back a phase that has
    already resolved attacks. Runs the SAME gate as the cast (spell_casting._gate_spell), fetches the
    player for_update ONCE (the cast reuses the returned row, so the lock is taken a single time), and
    returns it — or None when no player ability was declared (the common all-attacks phase locks
    nothing). Non-player abilities are wasted downstream, so they are not gated here."""
    player_abilities = [
        p.declaration.action
        for p in adv.packets
        if p.declaration.type is DeclarationType.ABILITY
        and p.declaration.action
        and (actor := state.get_participant(p.actor_id)) is not None
        and actor.type == "player"
    ]
    if not player_abilities:
        return None
    player = await queries.get_player(session.player_id, conn=conn, for_update=True)
    if player is None:
        raise ToolError(f"Unknown player: {session.player_id}")
    for action in player_abilities:
        cast_resolver._gate_spell(player, action)
    return player


async def _resolve_one_packet(
    session: SessionData,
    state,
    packet,
    *,
    mutations,
    queries,
    resolver,
    concentration_break_mod,
    conn=None,
    sink=None,
    cast_resolver=spell_casting,
    cast_outcome=None,
    player=None,
) -> dict:
    """Resolve a single initiative-ordered ResolutionPacket against ``state``.

    A declaration is *wasted* (resolved=False) when its actor or target is gone or
    has already fallen this phase, or its action isn't in the actor's pool — one bad
    or stale declaration never crashes the phase. Attack resolves through the shared
    attack resolver (carrying the target's phase AC modifier) and records the player's
    weapon-durability flags. Ability resolves through the shared cast logic (story-007,
    via _resolve_ability_packet), its CastResult stashed on ``cast_outcome`` for the
    phase loop to commit. Defend resolves as a no-op (its +2 AC was applied to
    state.ac_modifiers in the resolve_phase pre-pass). Interact/Maneuver/Retreat are
    modelled + initiative-ordered but their mechanical resolution lands in later M4.x."""
    attacker = state.get_participant(packet.actor_id)
    decl = packet.declaration

    if attacker is None or attacker.is_fallen:
        return {"actor_id": packet.actor_id, "resolved": False, "reason": "actor unavailable"}

    if decl.type is DeclarationType.DEFEND:
        return {
            "actor_id": packet.actor_id,
            "resolved": True,
            "declaration_type": str(decl.type),
            "ac_bonus": decl.ac_bonus,
        }

    if decl.type is DeclarationType.ABILITY:
        return await _resolve_ability_packet(
            session,
            attacker,
            decl,
            cast_resolver=cast_resolver,
            conn=conn,
            player=player,
            cast_outcome=cast_outcome if cast_outcome is not None else AbilityCastOutcome(),
        )

    if decl.type is not DeclarationType.ATTACK:
        # Non-attack declarations don't resolve mechanically yet, but a narrated rider
        # (e.g. Quick Change on a social INTERACT) still surfaces for the DM to voice.
        summary = {
            "actor_id": packet.actor_id,
            "resolved": False,
            "declaration_type": str(decl.type),
            "reason": f"{decl.type} resolution not yet implemented",
        }
        return _attach_riders(summary, attacker, decl)

    target = state.get_participant(decl.target_id) if decl.target_id else None
    action = _find_action(attacker, decl.action)
    if target is None:
        return {"actor_id": packet.actor_id, "resolved": False, "reason": f"target '{decl.target_id}' not found"}
    if target.is_fallen:
        return {"actor_id": packet.actor_id, "resolved": False, "reason": f"{target.name} already fell"}
    if action is None:
        return {"actor_id": packet.actor_id, "resolved": False, "reason": f"action '{decl.action}' not found"}

    # Enhancers EXPAND a single declaration: extra_attack/shield_bash turn one ATTACK into a
    # short attack sequence (still ONE declaration, never a second), narrated riders attach
    # below. attack_sequence is [action] when the actor has no mechanical enhancer (AC3: no
    # phantom expansion → the summary stays the flat single-attack shape).
    actions = combat_enhancers.attack_sequence(attacker.enhancers, action)
    # Encounter-context dramatic signals (M4.5, story-004) the per-attack resolver can't see:
    # the count of foes still standing as this declaration is resolved (==1 => last enemy), and
    # whether any attack has resolved this whole combat yet (the opening strike). Computed once
    # before the swing loop so all swings of an expanded sequence share one verdict.
    enemies_remaining = sum(1 for p in state.participants if p.type == "enemy" and not p.is_fallen)
    is_first_attack = not state.first_attack_resolved
    attack_summaries: list[dict] = []
    for act in actions:
        sub = await _resolve_attack_packet(
            session,
            attacker,
            act,
            target,
            target_ac_bonus=state.ac_modifiers.get(target.id, 0),
            enemies_remaining=enemies_remaining,
            is_first_attack_of_combat=is_first_attack,
            mutations=mutations,
            queries=queries,
            resolver=resolver,
            concentration_break_mod=concentration_break_mod,
            conn=conn,
            sink=sink,
        )
        attack_summaries.append(sub)
        # Preserve request_attack's old behavior: any player swing — hit OR miss — arms the
        # per-encounter weapon-durability accrual that end_combat applies. Only the extra
        # crit-vs-heavy-armor cost (2 hits) is gated on a critical hit landing.
        if attacker.type == "player":
            session.weapon_used_this_encounter = True
            if sub["hit"] and sub["critical"] and combat_resolution.is_heavily_armored(target.ac):
                session.weapon_crit_vs_heavy = True
        # An expanded sequence stops once the target drops — no swinging at a fallen foe.
        if target.is_fallen:
            break

    # The first attack of the combat has now resolved; flips the combat-scoped flag so a
    # later attack no longer earns the dramatic "first_attack" promotion (story-004).
    state.first_attack_resolved = True

    summary = dict(attack_summaries[0])
    if len(attack_summaries) > 1:
        # Report the expansion: per-attack detail under "attacks", flat keys aggregated.
        # Damage/hit/critical/concentration accumulate across swings; the target-state keys
        # (hp_status, fallen) must reflect the FINAL swing — the kill on the second hit, not
        # the goblin-still-up snapshot from the first — or the DM narrates a fallen foe alive.
        last = attack_summaries[-1]
        summary["attacks"] = attack_summaries
        summary["damage"] = sum(s["damage"] for s in attack_summaries)
        summary["hit"] = any(s["hit"] for s in attack_summaries)
        summary["critical"] = any(s["critical"] for s in attack_summaries)
        summary["target_hp_status"] = last["target_hp_status"]
        summary["target_fallen"] = last["target_fallen"]
        summary["concentration_broken"] = next(
            (s["concentration_broken"] for s in attack_summaries if s["concentration_broken"]), None
        )
        # Any swing being dramatic makes the declaration dramatic. Each swing rolls its
        # own d20 and runs its own killing-blow check, so a later swing can be dramatic
        # while the first is routine — take the FIRST dramatic swing's context so the
        # aggregated dramatic flag and its reason label never disagree (story-004).
        summary["dramatic"] = any(s["dramatic"] for s in attack_summaries)
        summary["context"] = next((s["context"] for s in attack_summaries if s["dramatic"]), "")
    summary["actor_id"] = packet.actor_id
    summary["resolved"] = True
    return _attach_riders(summary, attacker, decl)
