"""Per-packet/phase resolution helpers for the combat phase loop (split from
combat_turn.py to keep that file under the 500-line ceiling).

resolve_phase (in combat_turn) orchestrates the per-phase transaction; the
helpers here do the actual resolution work it drives: _prevalidate_ability_focus
gates player ability Focus before the loop, _resolve_one_packet dispatches a
single initiative-ordered packet to the right resolver (attack / ability /
de-escalate / defend), and _resolve_tick_saves resolves the Beat-4 save-to-clear
conditions the wrap surfaces. All are pure-ish helpers — they mutate in-memory
state and write through injected mutation/query modules, but own no transaction."""

from livekit.agents.llm import ToolError

import combat_enhancers
import combat_resolution
import conditions
import spell_casting
import spells
from combat_ability import (
    AbilityCastOutcome,
    _attach_riders,
    _find_action,
    _gate_ability_condition,
    _gate_deescalation,
    _resolve_ability_condition_packet,
    _resolve_ability_packet,
    _resolve_deescalation_packet,
    _resolve_enemy_condition_packet,
    condition_ability,
)
from combat_support import _resolve_attack_packet
from declarations import DeclarationType
from session_data import SessionData

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
        # Shared participant-save SSOT (roll_participant_save): builds player_data from the actor and
        # expands the 3-letter tick_save ("wis" -> "wisdom"). Engine-auto tick-clear: never spends the
        # actor's +1d4 (bonus_dice_eligible=False, M4.8 story-003), and include_proficiency=False keeps
        # the pre-M13 clear odds — folding proficiency in here would be an untested M4.3 balance shift.
        result = save_resolver.roll_participant_save(
            actor,
            event["save"],
            _CONDITION_CLEAR_DC,
            event["type"],
            bonus_dice_eligible=False,
            include_proficiency=False,
        )
        if result.success:
            actor.conditions = conditions.remove_condition(actor.conditions, event["type"])


async def _prevalidate_ability_focus(session, state, adv, *, conn, queries, cast_resolver):
    """Pre-validate every player ABILITY declaration's Focus BEFORE the resolution loop (AC2).

    An unaffordable in-combat ability must fail loud (ToolError) with NO state writes — and crucially
    before any OTHER actor's HP/durability write, so a bad ability never rolls back a phase that has
    already resolved attacks. Runs the SAME gate as the cast (spell_casting._gate_spell), fetches the
    player for_update ONCE (the cast reuses the returned row, so the lock is taken a single time), and
    returns it — or None when no player ability was declared (the common all-attacks phase locks
    nothing). Non-player abilities are wasted downstream, so they are not gated here."""
    player_ability_decls = [
        p.declaration
        for p in adv.packets
        if p.declaration.type is DeclarationType.ABILITY
        and p.declaration.action
        and (actor := state.get_participant(p.actor_id)) is not None
        and actor.type == "player"
    ]
    if not player_ability_decls:
        return None
    player = await queries.get_player(session.player_id, conn=conn, for_update=True)
    if player is None:
        raise ToolError(f"Unknown player: {session.player_id}")
    for decl in player_ability_decls:
        action = decl.action
        # Three non-spell-vs-spell ABILITY gates (pre-resolution, no writes): de_escalate (M4.6a)
        # has its own Focus+lockout gate; a non-spell condition ability (M4.8 story-005, e.g.
        # bard_inspire) gates its catalog Stamina/Focus; everything else is a spell-backed ability
        # gated against the spell catalog. _gate_spell would raise "Unknown spell" for the first two.
        if action.lower() == "de_escalate":
            _gate_deescalation(player, state)
        elif (cond_ability := condition_ability(action)) is not None:
            _gate_ability_condition(player, cond_ability)
            # Multi-target cap (M4.8 story-016): reject an over-cap / malformed multi-target ability
            # (e.g. bard_mass_inspire) HERE, before resolution writes — reusing the SAME targeting
            # SSOT the spell branch uses (normalize_target_list accepts Spell | Ability).
            if decl.target_ids:
                try:
                    spells.normalize_target_list(cond_ability, decl.target_id, decl.target_ids)
                except ValueError as e:
                    raise ToolError(str(e)) from e
        else:
            spell = cast_resolver._gate_spell(player, action)
            # Multi-target cap (M4.8 story-012): reject an over-cap / malformed multi-target spell
            # declaration HERE, before the resolution loop writes anything — reusing the targeting
            # SSOT. Spell-aware, so it belongs with the Focus gate, not in pure resolve_declaration.
            if decl.target_ids:
                try:
                    spells.normalize_target_list(spell, decl.target_id, decl.target_ids)
                except ValueError as e:
                    raise ToolError(str(e)) from e
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

    # Resolve the actor's pool action ONCE — reused by the enemy-condition branch and the ATTACK
    # path below so an ordinary enemy attack isn't scanned twice. Only ATTACK (any actor) and a
    # hostile-actor ABILITY (the enemy-condition case) need the pool lookup; a player/ally ABILITY is
    # a spell/ability id, not a pool action, so it stays None.
    action = (
        _find_action(attacker, decl.action)
        if decl.type is DeclarationType.ATTACK or (not attacker.is_ally and decl.type is DeclarationType.ABILITY)
        else None
    )

    # Enemy condition-infliction (M13): a HOSTILE actor (is_ally False — enemy or temporary_hollowed,
    # never a player/companion ally) whose action_pool entry carries applies_condition inflicts a
    # save-gated condition, routed on the ACTION FIELD, not the declaration type. The DM declares
    # enemy pool actions as ATTACK (system_prompts.py:235 — "Ability" is a spell/ability id the
    # caster knows, which pool actions are not), so gating this on ABILITY alone made the whole
    # feature a no-op in real play. Deterministic mechanics: the engine, not the LLM's type choice,
    # decides the effect. Fires for ATTACK or ABILITY; an action WITHOUT applies_condition falls
    # through to the normal attack/ability path. (The opening-strike dramatic beat stays with the
    # first real ATTACK — a save-based condition is not an attack roll, so it does not consume it.)
    if not attacker.is_ally and action is not None and action.get("applies_condition"):
        return await _resolve_enemy_condition_packet(session, attacker, decl, action, state=state, conn=conn)

    if decl.type is DeclarationType.ABILITY:
        # (Enemy condition-infliction ABILITY is handled by the type-agnostic branch above, which
        # routes both ATTACK and ABILITY enemy actions carrying applies_condition. The branches
        # below are the player-oriented paths.)
        # De-escalate (M4.6a story-004) is an ABILITY but resolves socially, not as a cast:
        # contested gate + one argument that can end combat. Its Focus/lockout were pre-gated
        # in _prevalidate_ability_focus, and ``player`` is the for_update row from there.
        if (decl.action or "").lower() == "de_escalate":
            return await _resolve_deescalation_packet(
                session, attacker, decl, state=state, conn=conn, player=player, sink=sink
            )
        # A non-spell condition ability (M4.8 story-005, e.g. bard_inspire) resolves via the dedicated
        # ability-condition path — deduct its cost and land the condition on the target participant —
        # NOT through _resolve_ability_packet (which casts a spell). Pre-gated in _prevalidate_ability_focus.
        cond_ability = condition_ability(decl.action)
        if cond_ability is not None:
            return await _resolve_ability_condition_packet(
                session, attacker, decl, cond_ability, state=state, conn=conn, player=player
            )
        return await _resolve_ability_packet(
            session,
            attacker,
            decl,
            state=state,
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
    # `action` was resolved once above (the single _find_action for this packet).
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
            combat_state=state,
            conn=conn,
            sink=sink,
        )
        attack_summaries.append(sub)
        # Consume the single-use beneficial die ONCE per declaration (M4.8 story-003): the swing
        # that rolled it signals consumed_conditions; remove them from the attacker so the next
        # swing of an expanded sequence sees a clean attacker and rolls no die. The first
        # consuming swing's removal makes every later swing's consumed_conditions empty, so this
        # fires at most once. Rides the phase's save_combat_state (no extra persist).
        if sub.get("consumed_conditions"):
            attacker.conditions = conditions.remove_conditions(attacker.conditions, sub["consumed_conditions"])
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
