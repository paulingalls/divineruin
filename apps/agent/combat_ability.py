"""In-combat ABILITY (cast) resolution helpers.

Splits the ability-cast concern out of combat_support (story-007): resolving an
in-combat ABILITY declaration through the shared cast logic, the side-channel that
carries the cast result back to the phase loop, action lookup, and enhancer-rider
attachment. Consumed by the phase loop (combat_turn)."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from livekit.agents.llm import ToolError

import abilities
import ability_persistence
import check_resolution
import combat_enhancers
import combat_resolution
import conditions
import event_types as E
import spell_casting
from combat_events import emit_or_publish
from dice import roll as dice_roll
from resource_costs import gate_pool
from rules_engine import attribute_modifier
from session_data import CombatParticipant, SessionData

if TYPE_CHECKING:
    from declarations import Declaration
    from spell_casting import CastResult

# Diplomat de-escalation (M4.6a story-004, spec game_mechanics_combat.md:175-183).
_DEESCALATE_FOCUS_COST = 3


def _lead_enemy(state):
    """The living enemy the Diplomat addresses: highest WIS resists hardest (spec L180)."""
    living = [p for p in state.participants if p.type == "enemy" and not p.is_fallen]
    if not living:
        return None
    return max(living, key=lambda e: e.attributes.get("wisdom", 10))


def _gate_deescalation(player: dict, state) -> None:
    """Declare-time fail-loud gate for de_escalate: one attempt per encounter, 3 Focus.

    Mirrors spell_casting._gate_spell's pre-resolution discipline — validate with NO state
    writes so a bad attempt never rolls back a phase that already resolved other actors."""
    if state.deescalation_used:
        raise ToolError("De-escalate can only be attempted once per encounter.")
    have = (player.get("focus") or {}).get("current", 0)
    if have < _DEESCALATE_FOCUS_COST:
        raise ToolError(f"De-escalate costs {_DEESCALATE_FOCUS_COST} Focus; you have {have}.")


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
) -> dict:
    """Resolve a de_escalate ABILITY in combat (M4.6a story-004).

    Focus + lockout are pre-validated at declare time (_gate_deescalation); here we spend the
    3 Focus, roll the contested CHA-vs-lead-enemy-WIS gate plus one argument, set the combat-end
    flags on CombatState, and emit the always-dramatic de_escalate DICE_ROLL. ``player`` is the
    for_update row from prevalidation (reused, so the lock is taken once). The flags are set on
    the phase loop's working ``state`` (the deep-copied next_state the wrap reads), NOT
    session.combat_state — that stays the pristine pre-phase copy until the tx commits."""
    if state is None or player is None:
        return {"actor_id": attacker.id, "resolved": False, "reason": "no active combat or player"}
    lead = _lead_enemy(state)
    if lead is None:
        return {
            "actor_id": attacker.id,
            "resolved": False,
            "declaration_type": str(decl.type),
            "reason": "no living enemy to de-escalate",
        }

    have = (player.get("focus") or {}).get("current", 0)
    await persistence.update_player_resources(session.player_id, focus=have - _DEESCALATE_FOCUS_COST, conn=conn)

    attrs = player.get("attributes", {})
    cha_total = dice_roll("d20", rng=rng).total + attribute_modifier(attrs.get("charisma", 10))
    enemy_wis_total = dice_roll("d20", rng=rng).total + attribute_modifier(lead.attributes.get("wisdom", 10))
    # Source the beneficial die (Inspired's +1d4) from the in-combat SSOT — the attacker
    # participant's conditions — not the stale DB row, so an in-combat-applied Inspired folds and
    # an OOC one cannot double-dip with a later attack swing (M4.8 story-011). Consume the signalled
    # die ONCE off the participant (mirrors the attack path, combat_packet.py); the mutation rides
    # the phase's save_combat_state, so there is no permanent +1d4.
    argument = check_resolution.resolve_skill_check_dc(
        {**player, "conditions": attacker.conditions}, "persuasion", combat_resolution.DEESCALATE_BASE_DC, rng
    )
    argument_total = argument.total
    if argument.consumed_conditions:
        attacker.conditions = conditions.remove_conditions(attacker.conditions, argument.consumed_conditions)

    outcome = combat_resolution.resolve_deescalation(
        cha_total=cha_total,
        enemy_wis_total=enemy_wis_total,
        argument_total=argument_total,
        base_dc=combat_resolution.DEESCALATE_BASE_DC,
    )
    state.deescalation_used = True
    if outcome.ends_combat:
        state.deescalated = True

    await emit_or_publish(
        sink,
        session.room,
        E.DICE_ROLL,
        {
            "roll_type": "de_escalate",
            "actor": attacker.name,
            "scene_entered": outcome.scene_entered,
            "success": outcome.success,
            "dramatic": outcome.dramatic,
            "context": outcome.context,
        },
        event_bus=session.event_bus,
    )
    session.record_event(
        f"{attacker.name} attempts de-escalation: {'combat ends' if outcome.ends_combat else 'combat continues'}"
    )
    return {
        "actor_id": attacker.id,
        "resolved": True,
        "declaration_type": str(decl.type),
        "action": "de_escalate",
        "deescalation": {
            "scene_entered": outcome.scene_entered,
            "success": outcome.success,
            "ends_combat": outcome.ends_combat,
            "narrative_cue": outcome.narrative_cue,
        },
    }


def _land_condition_on_one(
    state, target_id: str | None, attacker: CombatParticipant, cond_type: str, source: str
) -> bool:
    """Land a beneficial condition on ONE in-combat participant (M4.8). Self-target (``target_id``
    None) falls back to the caster; a given id is looked up on the working ``state``. Returns True
    iff it actually landed (``has_condition``) — a target not on the state, or an immunity no-op,
    returns False so the caller drops the buff signal. The mutation rides save_combat_state."""
    cond_target = attacker if target_id is None else state.get_participant(target_id)
    if cond_target is None:
        return False
    cond_target.conditions = conditions.apply_condition(cond_target.conditions, cond_type, source=source)
    return conditions.has_condition(cond_target.conditions, cond_type)


def land_condition_on_participant(
    state, attacker: CombatParticipant, decl: "Declaration", cond_type: str, source: str
) -> bool:
    """Single-target landing rule for the combat producers (the spell path in _resolve_ability_packet
    and the non-spell ability path in _resolve_ability_condition_packet): land ``cond_type`` on
    ``decl.target_id`` (self when absent). Returns True iff it landed. Thin wrapper over
    ``_land_condition_on_one`` (M4.8 story-012 extraction); back-compat for existing callers."""
    return _land_condition_on_one(state, decl.target_id, attacker, cond_type, source)


def land_condition_on_participants(
    state, attacker: CombatParticipant, decl: "Declaration", cond_type: str, source: str
) -> list[str]:
    """Land ``cond_type`` on EACH participant of a multi-target declaration (M4.8 story-012).

    Resolves the target list: ``decl.target_ids`` (order-preserving dedup) when present, else the
    single ``decl.target_id``, else the caster (self-cast). The cap was already enforced at the
    declare-gate (combat_packet via spells.normalize_target_list); dedup here just prevents
    double-voicing the same ally. Returns the participant ids the buff actually LANDED on (an id not
    on the working state, or an immunity no-op, is dropped) — the subset the DM should name."""
    if decl.target_ids:
        targets: list[str | None] = list(dict.fromkeys(decl.target_ids))
    elif decl.target_id is not None:
        targets = [decl.target_id]
    else:
        targets = [None]  # self-cast
    voiced: list[str] = []
    for tid in targets:
        if _land_condition_on_one(state, tid, attacker, cond_type, source):
            voiced.append(tid if tid is not None else attacker.id)
    return voiced


def condition_ability(action: str | None) -> "abilities.Ability | None":
    """The non-spell, condition-applying ABILITY for ``action``, or None.

    The in-combat ABILITY path resolves spells by default (via _gate_spell / _resolve_cast); a
    non-spell ability that PRODUCES a condition (M4.8 story-005, e.g. bard_inspire) takes the
    dedicated ability-condition path instead. An ability is on that path iff it carries
    ``applies_condition`` AND has no ``spell_id`` — a spell-backed condition ability keeps the
    spell path, where story-004's producer block already applies it (assumption 07d1a208794b).
    Returns None for an unknown action or any spell/non-condition ability."""
    if action is None:
        return None
    try:
        ability = abilities.get_ability(action)
    except ValueError:
        return None
    if ability.applies_condition is not None and ability.spell_id is None:
        return ability
    return None


def _gate_ability_condition(player: dict, ability: "abilities.Ability") -> None:
    """Declare-time fail-loud gate for a non-spell condition ability (M4.8 story-005): validate the
    ability's Stamina/Focus with NO writes, mirroring _gate_deescalation / _gate_spell so a bad
    declaration never rolls back a phase that already resolved other actors. resource_costs.gate_pool
    is the sole Focus/Stamina gate; the deduct happens in _resolve_ability_condition_packet."""
    gate_pool(player, "stamina", ability.cost.stamina, label=ability.name)
    gate_pool(player, "focus", ability.cost.focus, label=ability.name)


async def _deduct_ability_cost(session, player, ability, *, persistence, conn) -> None:
    """Spend a condition ability's Stamina/Focus via the gate_pool SSOT and persist (M4.8). Shared by
    the single- and multi-target resolve branches so the deduct lives once; gate_pool fail-louds if
    the cost can't be paid (already pre-gated at declare time)."""
    new_stamina = gate_pool(player, "stamina", ability.cost.stamina, label=ability.name)
    new_focus = gate_pool(player, "focus", ability.cost.focus, label=ability.name)
    if new_stamina is not None or new_focus is not None:
        await persistence.update_player_resources(session.player_id, stamina=new_stamina, focus=new_focus, conn=conn)


async def _resolve_ability_condition_packet(
    session: SessionData,
    attacker: CombatParticipant,
    decl: "Declaration",
    ability: "abilities.Ability",
    *,
    state,
    conn,
    player: dict | None,
    persistence=ability_persistence,
) -> dict:
    """Resolve a non-spell condition-applying ABILITY in combat (M4.8 story-005, e.g. bard_inspire).

    Resolve the TARGET participant FIRST: self-target (no target_id) is the caster (always present);
    a given target_id that's not on the working state, or one already fallen, WASTES the declaration
    (resolved:False) WITHOUT deducting — you can't buff a target that left or a corpse, and a wasted
    declaration must never burn the ability's Stamina/Focus (mirrors the attack path's wasted-target
    guards). Only once a live target is confirmed do we deduct the cost (pre-gated at declare time via
    _gate_ability_condition) and land applies_condition on it via the shared helper — the mutation
    rides the phase save_combat_state (no extra write). ``player`` is the for_update row from
    prevalidation, reused so the lock is taken once."""
    if state is None or player is None:
        return {"actor_id": attacker.id, "resolved": False, "reason": "no active combat or player"}

    # applies_condition is non-None on this path (condition_ability selected it); the resolved
    # ability id is the source (== decl.action by the lookup invariant).
    cond_type = ability.applies_condition

    # Multi-target (M4.8 story-016, e.g. bard_mass_inspire): the cap was validated at the
    # declare-gate (spells.normalize_target_list). Deduct once, land on EACH live ally, and voice
    # the landed set (condition_targets) — mirroring the multi-target spell path. A target gone by
    # resolve time is dropped (partial landing); an all-off-state list lands nothing but still
    # spends the cost (the spell-path convention — the declaration committed to the action).
    if decl.target_ids:
        await _deduct_ability_cost(session, player, ability, persistence=persistence, conn=conn)
        summary = {
            "actor_id": attacker.id,
            "resolved": True,
            "declaration_type": str(decl.type),
            "action": ability.id,
        }
        if cond_type is not None:
            voiced = land_condition_on_participants(state, attacker, decl, cond_type, source=ability.id)
            if voiced:
                summary["condition_applied"] = cond_type
                summary["condition_targets"] = voiced
        return summary

    # Single-target (story-005): a given target_id that's not on the working state, or already
    # fallen, WASTES the declaration (resolved:False) WITHOUT deducting — you can't buff a target
    # that left or a corpse, and a wasted declaration must never burn the cost.
    cond_target = attacker if decl.target_id is None else state.get_participant(decl.target_id)
    if cond_target is None:
        return {
            "actor_id": attacker.id,
            "resolved": False,
            "declaration_type": str(decl.type),
            "reason": f"target '{decl.target_id}' not found",
        }
    if cond_target.is_fallen:
        return {
            "actor_id": attacker.id,
            "resolved": False,
            "declaration_type": str(decl.type),
            "reason": f"{cond_target.name} already fell",
        }

    await _deduct_ability_cost(session, player, ability, persistence=persistence, conn=conn)

    summary = {
        "actor_id": attacker.id,
        "resolved": True,
        "declaration_type": str(decl.type),
        "action": ability.id,
    }
    if cond_type is not None and land_condition_on_participant(state, attacker, decl, cond_type, source=ability.id):
        summary["condition_applied"] = cond_type
    return summary


@dataclass
class AbilityCastOutcome:
    """Side-channel carrying an in-loop ABILITY cast's ``CastResult`` back to the phase loop.

    At most one player ability resolves per phase (one declaration per participant), so a single
    slot suffices. The loop reads ``cast_result`` post-commit to seed the WRAP resonance, sync
    concentration in-memory, and flush the cast's deferred client events — all of which must happen
    after the phase tx commits (story-007). ``cast_result`` stays ``None`` when no ability resolved."""

    cast_result: "CastResult | None" = None


async def _resolve_ability_packet(
    session: SessionData,
    attacker: CombatParticipant,
    decl,
    *,
    state,
    cast_resolver,
    conn,
    player: dict | None,
    cast_outcome: AbilityCastOutcome,
) -> dict:
    """Resolve one in-combat ABILITY declaration through the shared cast logic (story-007).

    Player-gated: only the player carries a Focus pool + resonance track, so a non-player ABILITY
    (or one missing its action) is a *wasted* packet — enemy/companion casting is later M4.x work.
    Delegates to ``cast_resolver._resolve_cast`` with the cast's own RESONANCE_CHANGED suppressed
    (in combat the phase WRAP push is the single authoritative HUD update), stashing the returned
    CastResult on ``cast_outcome`` for the loop to commit. The returned summary carries the spell
    packet for the DM plus any narrated enhancer riders."""
    if attacker.type != "player":
        return {
            "actor_id": attacker.id,
            "resolved": False,
            "declaration_type": str(decl.type),
            "reason": "ability resolution not yet implemented for non-player actors",
        }
    if not decl.action:
        return {
            "actor_id": attacker.id,
            "resolved": False,
            "declaration_type": str(decl.type),
            "reason": "ability declaration missing an action",
        }

    result = await cast_resolver._resolve_cast(
        session,
        decl.action,
        conn=conn,
        player=player,
        target_id=decl.target_id,
        suppress_resonance_changed=True,
    )
    cast_outcome.cast_result = result
    # Sync concentration into the session SSOT IN-LOOP (not post-commit): a lower-initiative enemy
    # attack later this same phase runs break_concentration_on_damage, which reads the in-memory
    # session.concentration to pick which spell to save for and to clear on a failed save. A
    # post-commit sync would leave it stale — the break would save against the OLD spell and, on a
    # break, write None to the DB (clearing the just-cast spell) while the post-commit sync forced
    # memory back to the new spell, diverging from the DB (story-007). _CombatScratchSnapshot
    # captures concentration, so this in-tx mutation is reverted if the phase rolls back.
    if result.concentration_spell_id is not spell_casting._UNCHANGED:
        session.concentration.spell_id = cast("str | None", result.concentration_spell_id)
    # Beneficial-condition PRODUCER (M4.8 story-004), in-combat half. _resolve_cast surfaces the
    # produced condition as packet.condition_applied (the OOC players.data write is gated off in
    # combat). In combat the working state is the SSOT, so land it on the TARGET participant here —
    # the mutation rides this phase's save_combat_state. Self-cast (no target_id) falls back to the
    # caster; a target not on the working state narrates nothing (condition_applied dropped) rather
    # than crashing the phase, mirroring the wasted-declaration guards. source=decl.action is the
    # spell id (matching the OOC source=spell_id). Resolved here where attacker/decl/result are
    # already in scope — no outcome re-read in the dispatcher.
    cond_type = result.packet.get("condition_applied")
    if cond_type:
        if decl.target_ids:
            # Multi-target (M4.8 story-012): land on EACH ally participant (cap already enforced at
            # the declare-gate). Surface the voiced ids so the DM names each blessed companion; drop
            # the signal entirely if NONE landed (all off-state / immune).
            voiced = land_condition_on_participants(state, attacker, decl, cond_type, source=decl.action)
            if voiced:
                result.packet["condition_targets"] = voiced
            else:
                result.packet.pop("condition_applied", None)
        elif not land_condition_on_participant(state, attacker, decl, cond_type, source=decl.action):
            # Target gone, or apply no-op'd (immunity gate) — don't narrate a buff that never landed.
            result.packet.pop("condition_applied", None)
    summary = {
        "actor_id": attacker.id,
        "resolved": True,
        "declaration_type": str(decl.type),
        "action": decl.action,
        "cast": result.packet,
    }
    return _attach_riders(summary, attacker, decl)


def _find_action(participant, action_name) -> dict | None:
    """Find the named action in a participant's action_pool (case-insensitive)."""
    if not action_name:
        return None
    wanted = str(action_name).lower()
    for a in participant.action_pool:
        if a.get("name", "").lower() == wanted:
            return a
    return None


def _attach_riders(summary: dict, attacker, decl) -> dict:
    """Add the actor's narrated enhancer riders to a packet summary, if any.

    Riders are descriptive (non-mechanical) — they carry no HP/AC effect, just the DM
    cue for an enhancer's expansion (Cunning Action's dash/disengage/hide, Hit and Run,
    Command Lesser, Quick Change). Omitted entirely when the actor has none, so a
    no-enhancer declaration keeps its flat summary (AC3: no phantom expansion)."""
    riders = combat_enhancers.declaration_riders(attacker.enhancers, decl)
    if riders:
        summary["riders"] = riders
    return summary
