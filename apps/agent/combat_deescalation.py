"""In-combat Tier-3 GROUP de-escalation resolver (M15 story-002).

Split out of combat_ability (sprint-036 retro debt dafdf5575b0f): the
social/de-escalation cluster is a self-contained concern, unrelated to the
ability-cast / condition resolvers that remain there."""

from dataclasses import asdict

from livekit.agents.llm import ToolError

import ability_persistence
import check_resolution
import combat_resolution
import communication_voice_rules
import condition_voice_rules
import conditions
import event_types as E
import social_resolution
from combat_events import emit_or_publish
from condition_restrictions import cannot_act
from declarations import DeclarationType
from session_data import CombatParticipant, CombatState, SessionData
from skill_fate import SkillScope, StaleSkillOperation

# Diplomat de-escalation (M4.6a story-004, spec game_mechanics_combat.md:175-183).
_DEESCALATE_FOCUS_COST = 3
# Tier-3 scene round cap (M15 story-002, spec §Social Encounter Resolution): a full de-escalation
# argues over several rounds, but a group that hasn't yielded by here has stopped listening.
MAX_DEESCALATION_ROUNDS = 4


def eligible_argument_targets(state, speaker_id):
    targets = [
        p
        for p in state.participants
        if p.type == "enemy"
        and not p.is_fallen
        and state.deescalation_scene.cumulative_shift.get(p.id, 0) < combat_resolution.SURRENDER_THRESHOLD
    ]
    for target in targets:
        communication_voice_rules.actor_conditions(state, target.id)
    communication_voice_rules.require_source(state, speaker_id)
    eligible = [target for target in targets if communication_voice_rules.can_hear(state, target.id)]
    if not eligible:
        raise communication_voice_rules.DeliveryRefused("No eligible enemies can hear the argument")
    return eligible


def _gate_deescalation(player: dict, state, *, round_counter: int | None = None) -> None:
    """Declare-time fail-loud gate for de_escalate: round cap + 3 Focus, with NO state writes.

    Mirrors spell_casting._gate_spell's pre-resolution discipline — validate with NO state writes so
    a bad attempt never rolls back a phase that already resolved other actors. The Tier-3 scene runs
    multiple rounds (M15 story-002), so the once-per-encounter MVP lockout becomes a per-round cap:
    once the scene has run MAX_DEESCALATION_ROUNDS rounds the group won't hear more. Focus is still
    spent (and gated) per round."""
    current_round = state.deescalation_scene.round_counter if round_counter is None else round_counter
    if current_round >= MAX_DEESCALATION_ROUNDS:
        raise ToolError("The enemies have stopped listening — no more arguments will land.")
    have = (player.get("focus") or {}).get("current", 0)
    if have < _DEESCALATE_FOCUS_COST:
        raise ToolError(f"De-escalate costs {_DEESCALATE_FOCUS_COST} Focus; you have {have}.")


def _validate_argument_type(decl) -> str | None:
    """Fail-loud (NO writes) validation of a de_escalate declaration's Tier-3 argument category.

    Returns the category (None is a Tier-1 neutral argument, no DC swing); a non-None value must be
    canonical (social_resolution.ARGUMENT_TYPES) or the DM erred — raise a ToolError so the DM
    re-prompts. Called at the declare-time gate (before any actor resolves) so a bad category never
    rolls back a phase that already wrote other actors' HP/Focus; the packet re-checks defensively
    for direct callers."""
    argument_type = getattr(decl, "argument_type", None)
    if argument_type is not None and argument_type not in social_resolution.ARGUMENT_TYPES:
        raise ToolError(f"Unknown argument_type {argument_type!r}; expected one of {social_resolution.ARGUMENT_TYPES}.")
    return argument_type


async def _resolve_deescalation_packet(
    session: SessionData,
    attacker: CombatParticipant,
    decl,
    *,
    state,
    conn,
    player: dict | None,
    sink=None,
    persistence=ability_persistence,
    rng=None,
    progress=None,
) -> dict:
    """Resolve ONE round of a Tier-3 GROUP de-escalation in combat (M15 story-002).

    A Diplomat argues the WHOLE living enemy group at once: Focus + the round cap are pre-validated
    at declare time (_gate_deescalation); here we spend the 3 Focus, roll ONE persuasion total for
    the round, then apply that same argument to EACH living enemy INDEPENDENTLY — every enemy's
    disposition shifts by its own resistance profile (combat_resolution.resolve_argument_round),
    accumulating per enemy across rounds in ``state.deescalation_scene``. When the whole living group
    has crossed the surrender threshold, ``state.deescalated`` flips and the phase _wrap ends combat
    "deescalated"; a partial group leaves it False and the scene rides to the next round. ``player``
    is the for_update row from prevalidation (reused, so the lock is taken once).

    All mutations land on the phase loop's working ``state`` (the deep-copied next_state the wrap
    reads) — the flags AND the scene maps ride the phase's save_combat_state; we never write
    session.combat_state directly (it stays the pristine pre-phase copy until the tx commits)."""
    if state is None or player is None:
        return {"actor_id": attacker.id, "resolved": False, "reason": "no active combat or player"}

    # Early-out (finding #4): an earlier de_escalate packet this phase (a second Diplomat) may have
    # already ended the scene. Once ``deescalated`` is set, a further argument is a no-op — never spend
    # Focus or roll for a group that has already stood down.
    if state.deescalated:
        return {
            "actor_id": attacker.id,
            "resolved": False,
            "declaration_type": str(decl.type),
            "reason": "the group has already stood down",
        }

    living = [p for p in state.participants if p.type == "enemy" and not p.is_fallen]
    if not living:
        return {
            "actor_id": attacker.id,
            "resolved": False,
            "declaration_type": str(decl.type),
            "reason": "no living enemy to de-escalate",
        }

    # Re-validate the Tier-3 argument category (shape-only threaded by resolve_declaration). In real
    # play this already fired at the declare-time gate (_prevalidate_ability_focus) with NO writes, so
    # a bad category never reaches here mid-phase; the check stays for direct callers/tests as a
    # defensive fail-loud boundary before any Focus spend.
    targets = eligible_argument_targets(state, attacker.id)
    pre_phase_round = (
        session.combat_state.deescalation_scene.round_counter
        if isinstance(session.combat_state, CombatState)
        else state.deescalation_scene.round_counter
    )
    argument_type = _validate_argument_type(decl)

    if progress is not None and progress.deescalation_round is not None:
        pre_phase_round = progress.deescalation_round
    _gate_deescalation(player, state, round_counter=pre_phase_round)

    async def roll_argument():
        have = (player.get("focus") or {}).get("current", 0)
        await persistence.update_player_resources(attacker.id, focus=have - _DEESCALATE_FOCUS_COST, conn=conn)
        return check_resolution.resolve_skill_check_dc(
            condition_voice_rules.roll_data(player, state, attacker.id),
            "persuasion",
            combat_resolution.DEESCALATE_BASE_DC,
            rng,
            ally_present=session.allies_present_for(attacker.id),
            natural_terrain=False,
            hearing_only=False,
        )

    if progress is not None:
        scope = SkillScope.capture(session, attacker.id)
        argument = await progress.skill(session, attacker.id, roll_argument)
        if argument is None:
            progress.steps["argument"] = {
                "scope": asdict(scope),
                "targets": [target.id for target in targets],
                "argument_type": argument_type,
                "round": pre_phase_round,
            }
            return {}
    else:
        argument = await roll_argument()

    return await _finish_argument(
        session, state, attacker, targets, living, argument, argument_type, pre_phase_round, sink
    )


async def resume_deescalation(session, state, actor_id, decl, player, *, progress, sink):
    prepared = progress.steps.pop("argument")
    scope = SkillScope.restored(prepared["scope"])
    assert scope.roller_id == actor_id
    actor = state.get_participant(actor_id)
    try:
        scope.validate(session)
        if actor is None or not actor.is_ally or actor.is_fallen or player is None:
            raise StaleSkillOperation("The original speaker is unavailable.")
        scope.validate_location(actor_id, player)
        if blocked := cannot_act(actor.conditions):
            raise StaleSkillOperation(f"The original speaker is {blocked[0]}.")
        if decl is None or decl.type is not DeclarationType.ABILITY or (decl.action or "").lower() != "de_escalate":
            raise StaleSkillOperation("The original argument is no longer declared.")
        if state.deescalated:
            raise StaleSkillOperation("The group has already stood down.")
        eligible = {target.id: target for target in eligible_argument_targets(state, actor_id)}
        targets = [eligible[enemy_id] for enemy_id in prepared["targets"] if enemy_id in eligible]
        if not targets:
            raise StaleSkillOperation("The original enemies can no longer hear the argument.")
    except (StaleSkillOperation, communication_voice_rules.DeliveryRefused) as error:
        progress.steps.pop("skill")
        progress.phase.kept = None
        return {"actor_id": actor_id, "resolved": False, "outcome": "cancelled", "reason": str(error)}

    argument = progress.take_skill()
    assert argument is not None
    living = [p for p in state.participants if p.type == "enemy" and not p.is_fallen]
    return await _finish_argument(
        session,
        state,
        actor,
        targets,
        living,
        argument,
        prepared["argument_type"],
        prepared["round"],
        sink,
    )


async def _finish_argument(session, state, attacker, targets, living, argument, argument_type, pre_phase_round, sink):
    argument_total = argument.total
    if argument.consumed_conditions:
        attacker.conditions = conditions.remove_conditions(attacker.conditions, argument.consumed_conditions)

    # Per-enemy INDEPENDENT resolution: each enemy argues from its OWN accumulated disposition +
    # cumulative shift, swung by its OWN resistance_tags. Write the running maps back onto the scene.
    scene = state.deescalation_scene
    # Argue ONLY the not-yet-surrendered enemies (finding #2): once an enemy has crossed the surrender
    # threshold it is LATCHED — leaving it out of this round means a later bad roll can never regress it
    # below the threshold, so the whole-group gate can actually coincide. Combined with the resolver's
    # floor-at-0 (finding #1), a hostile holdout's progress can't bank negative either.
    per_enemy: list[dict] = []
    for e in targets:
        disposition = scene.enemy_dispositions.get(e.id, "hostile")
        outcome = combat_resolution.resolve_argument_round(
            disposition=disposition,
            argument_type=argument_type,
            resistance_tags=tuple(e.resistance_tags),
            roll_total=argument_total,
            cumulative_shift=scene.cumulative_shift.get(e.id, 0),
        )
        scene.cumulative_shift[e.id] = outcome.new_cumulative_shift
        scene.enemy_dispositions[e.id] = outcome.new_disposition
        per_enemy.append(
            {
                "id": e.id,
                "disposition": outcome.new_disposition,
                "cumulative_shift": outcome.new_cumulative_shift,
                "surrendered": outcome.surrendered,
            }
        )

    # Advance the SCENE round AT MOST ONCE per phase (finding #3): the round_counter models scene
    # rounds (phases), not de_escalate packets. Two Diplomats declaring in one phase argue the SAME
    # round — if each packet incremented, they would together push round_counter past the declare-time
    # cap. ``session.combat_state`` is the pristine pre-phase copy during resolution (the working
    # ``state`` is a deep copy), so a working counter still equal to the pre-phase value means no
    # earlier de_escalate advanced it this phase. When the session isn't a real CombatState (unit
    # drivers that pass ``state`` directly), fall back to always advancing — one packet per call there.
    if scene.round_counter == pre_phase_round:
        scene.round_counter += 1
    # Whole-group surrender: combat ends only when EVERY living enemy has crossed the threshold
    # (spec §Social Encounter Resolution). A partial group leaves ``deescalated`` False — the scene
    # persists and the next round argues the holdouts from their accumulated dispositions.
    state.deescalated = bool(living) and all(
        scene.cumulative_shift.get(e.id, 0) >= combat_resolution.SURRENDER_THRESHOLD for e in living
    )

    # Total living enemies at/over the threshold this round — includes latched holdouts not re-argued,
    # so the DM hears true group progress, not just this round's fresh yields.
    surrendered_count = sum(
        1 for e in living if scene.cumulative_shift.get(e.id, 0) >= combat_resolution.SURRENDER_THRESHOLD
    )
    # Always-dramatic (M4.5 de_escalate): every round of the scene surfaces on the HUD.
    await emit_or_publish(
        sink,
        session.room,
        E.DICE_ROLL,
        {
            "roll_type": "de_escalate",
            "actor": attacker.name,
            "round": scene.round_counter,
            "surrendered": surrendered_count,
            "living": len(living),
            "ends_combat": state.deescalated,
            "dramatic": True,
            "context": "de_escalate",
        },
        event_bus=session.event_bus,
    )
    session.record_event(
        f"{attacker.name} argues the group down (round {scene.round_counter}): "
        f"{surrendered_count}/{len(living)} yielding" + (" — combat ends" if state.deescalated else "")
    )
    return {
        "actor_id": attacker.id,
        "resolved": True,
        "declaration_type": str(DeclarationType.ABILITY),
        "action": "de_escalate",
        **({"gift_name": argument.gift_name} if argument.gift_name else {}),
        "deescalation": {
            "round": scene.round_counter,
            "ends_combat": state.deescalated,
            "per_enemy": per_enemy,
        },
    }
