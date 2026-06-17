"""Combat phase-loop tools — declare_phase, resolve_phase — plus the shared
_resolve_attack_packet resolver they drive (M4.1, story-003). request_death_save
lives in combat_death_save.py (story-004 split, debt faa6dd19ab64)."""

import json
import logging

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import check_resolution
import combat_enhancers
import combat_phase
import combat_resolution
import concentration_break
import db
import db_mutations
import db_mutations_resonance
import db_queries
import event_types as E
import resonance_events
from combat_end import _end_combat_db, _end_combat_finish
from combat_events import EventSink, emit_or_publish
from combat_support import (
    _accrue_durability,
    _attach_riders,
    _find_action,
    _find_equipped,
    _publish_sounds,
    _require_combat,
)
from db_errors import db_tool
from declarations import DeclarationType
from session_data import SessionData
from tool_support import (
    SOUND_ATTACK_CRITICAL,
    SOUND_ATTACK_HIT,
    SOUND_ATTACK_MISS,
    SOUND_HEARTBEAT,
    SOUND_PLAYER_FALLEN,
)

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
    per-actor resolution packets to narrate plus any death saves the player owes."""
    return await _resolve_phase_impl(context)


async def _resolve_phase_impl(
    context: RunContext[SessionData],
    *,
    mutations=db_mutations,
    queries=db_queries,
    resolver=check_resolution,
    concentration_break_mod=concentration_break,
    resonance_mutations=db_mutations_resonance,
    resonance_events_mod=resonance_events,
    db_mod=db,
) -> str | tuple:
    logger.info("resolve_phase called")
    session: SessionData = context.userdata

    cs = _require_combat(session)
    if cs.beat != combat_phase.PhaseBeat.RESOLUTION:
        raise ToolError(f"Not at the resolution beat (current beat: {cs.beat}). Call declare_phase first.")

    # One transaction spans every DB write of the phase — per-packet HP + durability, the
    # per-phase Resonance decay, and the trailing save_combat_state — so a mid-phase failure
    # rolls back atomically and players/items can never diverge from the combat_instances JSONB
    # SSOT (debt 084c7d0bc457). Event publishes inside the loop stay optimistic: a rolled-back
    # phase may have emitted DICE_ROLL/ITEM_DURABILITY_HIT, but a mid-phase DB error aborts the
    # turn regardless. The in-memory Resonance sync + HUD publish run AFTER commit (below).
    pending_resonance: int | None = None
    end_data: dict | None = None
    # Buffer every client event the phase emits; flush only AFTER the tx commits so a rolled-back
    # phase never leaks a phantom DICE_ROLL/ITEM_DURABILITY_HIT/sound (concern 03f2907d9c93).
    sink = EventSink()
    async with db_mod.transaction() as conn:
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
                )
            )

        # Beat 3 (narration) is an engine no-op; Beat 4 (wrap) computes the end-condition,
        # death saves due, and the per-phase Resonance decay signal.
        state, _narr = combat_phase.advance_combat_phase(state)
        state, wrap_adv = combat_phase.advance_combat_phase(state)
        wrap = wrap_adv.wrap

        ended_outcome = wrap.outcome if (wrap is not None and wrap.combat_ended and wrap.outcome) else None
        if ended_outcome is None:
            # Combat continues: shed one step of Resonance per phase. WRAP is the canonical
            # combat decay clock (decision resonance-decay-phase-canonical) — cast-paced decay
            # is already suppressed in combat (spell_casting), so this never double-decays.
            # Persist only when the value actually moved (a 0 floor stays silent); the in-memory
            # sync + HUD push happen post-commit so a rolled-back phase shows no decay.
            if wrap is not None and wrap.resonance_decay:
                new_resonance = max(0, session.resonance.current - wrap.resonance_decay)
                if new_resonance != session.resonance.current:
                    pending_resonance = new_resonance
                    await resonance_mutations.update_player_resonance(session.player_id, new_resonance, conn=conn)
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

    # Beat 4 end-condition: the engine reports victory (all enemies fallen) or defeat (the player
    # has died). end_combat's DB writes already committed inside the phase tx above; now apply its
    # in-memory teardown (clear combat_state, reset encounter flags) and return the handoff.
    if ended_outcome is not None:
        logger.info("resolve_phase: engine end-condition %s -> end_combat", ended_outcome)
        assert end_data is not None  # set in the tx whenever ended_outcome is not None
        return _end_combat_finish(session, state, ended_outcome, end_data)

    if pending_resonance is not None:
        session.resonance.current = pending_resonance
        await resonance_events_mod.publish_resonance_changed(session)

    response = {
        "beat": state.beat,
        "round": state.round_number,
        "packets": packet_summaries,
        "death_saves_due": wrap.death_saves_due if wrap else [],
    }
    logger.info(
        "resolve_phase result: beat=%s, round=%d, packets=%d", state.beat, state.round_number, len(packet_summaries)
    )
    return json.dumps(response)


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
) -> dict:
    """Resolve a single initiative-ordered ResolutionPacket against ``state``.

    A declaration is *wasted* (resolved=False) when its actor or target is gone or
    has already fallen this phase, or its action isn't in the actor's pool — one bad
    or stale declaration never crashes the phase. Attack resolves through the shared
    attack resolver (carrying the target's phase AC modifier) and records the player's
    weapon-durability flags. Defend resolves as a no-op (its +2 AC was applied to
    state.ac_modifiers in the resolve_phase pre-pass). Ability/Interact/Maneuver/Retreat
    are modelled + initiative-ordered but their mechanical resolution lands later
    (Ability → story-007; the rest in M4.x)."""
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
    attack_summaries: list[dict] = []
    for act in actions:
        sub = await _resolve_attack_packet(
            session,
            attacker,
            act,
            target,
            target_ac_bonus=state.ac_modifiers.get(target.id, 0),
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
    summary["actor_id"] = packet.actor_id
    summary["resolved"] = True
    return _attach_riders(summary, attacker, decl)


async def _resolve_attack_packet(
    session: SessionData,
    attacker,
    action: dict,
    target,
    *,
    target_ac_bonus: int = 0,
    shield_reaction: str | None = None,
    mutations=db_mutations,
    queries=db_queries,
    resolver=check_resolution,
    concentration_break_mod=concentration_break,
    conn=None,
    sink=None,
) -> dict:
    """Resolve ONE declared attack against CombatParticipant HP.

    Mutates ``target`` in place (hp_current, is_fallen), publishes the attack's
    DICE_ROLL, sounds, and any durability hits in strike order, and returns a
    response dict for the caller (a per-packet narration summary). It does NOT
    persist — the caller owns one ``save_combat_state`` per phase so the multi-packet
    phase loop persists exactly once. ``attacker``/``target`` are CombatParticipants;
    ``action`` is an entry from the attacker's action_pool (weapon-shaped).

    ``shield_reaction`` is a forward seam for the M4.x reaction-window feature
    (combat_phase's ``reactions_available``): when a future declaration spends a
    shield reaction it threads the shield name here to accrue shield durability. The
    live phase loop (``_resolve_one_packet``) does not yet declare reactions, so it
    is always ``None`` on the live path today; the accrual branch is exercised by
    test_combat_durability."""
    attacker_data = {
        "attributes": attacker.attributes,
        "level": attacker.level,
    }

    # ``target_ac_bonus`` is the target's phase-scoped AC modifier (Defend's +2, M4.2);
    # the live caller passes state.ac_modifiers[target.id]. Defaults to 0 for direct callers.
    effective_ac = target.ac + target_ac_bonus
    attack_result = resolver.resolve_attack(
        attacker_data,
        action,
        effective_ac,
        target.hp_current,
    )

    # Update target HP
    target.hp_current = attack_result.target_hp_remaining

    # Determine sounds
    sounds: list[str] = []
    if attack_result.critical_success:
        sounds.append(SOUND_ATTACK_CRITICAL)
    elif attack_result.hit:
        sounds.append(SOUND_ATTACK_HIT)
    else:
        sounds.append(SOUND_ATTACK_MISS)

    # Check HP thresholds
    hp_status = combat_resolution.hp_threshold_status(target.hp_current, target.hp_max)
    if target.hp_current <= 0:
        target.is_fallen = True
        sounds.append(SOUND_PLAYER_FALLEN)
        # Handle companion KO
        if target.type == "companion" and session.companion and target.id == session.companion.id:
            session.companion.is_conscious = False
            session.record_companion_memory(f"{target.name} was knocked unconscious in combat")
    elif hp_status in ("bloodied", "critical"):
        sounds.append(SOUND_HEARTBEAT)

    # Update DB if target is a player
    if target.type == "player":
        await mutations.update_player_hp(target.id, target.hp_current, conn=conn)

    # Combat damage is the canonical concentration-break trigger: a concentrating player who takes
    # damage rolls a CON save (DC scales with the damage); failing it — or being dropped to 0 HP
    # (incapacitated) — ends concentration. The helper no-ops when the player isn't concentrating
    # or the attack dealt no damage; its return (the broken spell id, or None) is narrated below.
    concentration_broken = None
    if target.type == "player":
        concentration_broken = await concentration_break_mod.break_concentration_on_damage(
            session, attack_result.damage, incapacitated=target.hp_current <= 0
        )

    # Publish events (buffered into ``sink`` during the phase tx; released post-commit)
    await emit_or_publish(
        sink,
        session.room,
        E.DICE_ROLL,
        {
            "roll_type": "attack",
            "attacker": attacker.name,
            "hit": attack_result.hit,
            "roll": attack_result.roll,
            "damage": attack_result.damage,
            "critical": attack_result.critical_success,
        },
        event_bus=session.event_bus,
    )
    await _publish_sounds(session, sounds, sink=sink)

    # Accrue durability on the player's equipped armor (1 hit per damage taken),
    # and on a shield when the player spends a shield reaction. Hollow zones double.
    # Runs after the attack's DICE_ROLL so ITEM_DURABILITY_HIT follows the strike.
    durability_results: dict = {}
    if target.type == "player" and attack_result.hit:
        inventory = await queries.get_player_inventory(target.id, conn=conn)
        is_hollow = combat_resolution.is_hollow_zone(session.corruption_level)
        armor = _find_equipped(inventory, "armor")
        if armor is not None:
            durability_results["armor"] = await _accrue_durability(
                session, target.id, armor, 1, is_hollow_zone=is_hollow, conn=conn, sink=sink
            )
        if shield_reaction:
            shield = _find_equipped(inventory, "shield")
            if shield is not None:
                durability_results["shield"] = await _accrue_durability(
                    session, target.id, shield, 1, is_hollow_zone=is_hollow, conn=conn, sink=sink
                )

    hit_miss = "hit" if attack_result.hit else "miss"
    session.record_event(f"{attacker.name} attacks {target.name}: {hit_miss}, {attack_result.damage} damage")

    response = {
        "attacker": attacker.name,
        "action": action.get("name", ""),
        "target": target.name,
        "hit": attack_result.hit,
        "roll": attack_result.roll,
        "attack_total": attack_result.attack_total,
        "target_ac": effective_ac,
        "damage": attack_result.damage,
        "damage_type": attack_result.damage_type,
        "critical": attack_result.critical_success,
        "target_hp_status": hp_status,
        "target_fallen": target.is_fallen,
        "narrative_hint": attack_result.narrative_hint,
        "durability": durability_results,
        "concentration_broken": concentration_broken,
    }
    logger.info(
        "resolve_attack_packet result: %s → %s, %s, damage=%d, hp_status=%s",
        attacker.name,
        target.name,
        hit_miss,
        attack_result.damage,
        hp_status,
    )
    return response
