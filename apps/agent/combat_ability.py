"""In-combat ABILITY (cast) resolution helpers.

Splits the ability-cast concern out of combat_support (story-007): resolving an
in-combat ABILITY declaration through the shared cast logic, the side-channel that
carries the cast result back to the phase loop, action lookup, and enhancer-rider
attachment. Consumed by the phase loop (combat_turn)."""

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, cast

from livekit.agents.llm import ToolError

import abilities
import ability_persistence
import architect_reaction
import combat_ability_save
import combat_enhancers
import combat_hollow_resonance
import combat_spell_damage
import combat_spell_heal
import combat_veilrender
import combat_voice_rules
import condition_voice_rules
import db_queries
import spell_casting
from combat_ability_gate import DeclaredAbility
from combat_condition_landing import (
    _land_condition_on_one,
    land_condition_on_participant,
    land_condition_on_participants,
)
from combat_down import damage_target_unavailable
from combat_structures import blocked_reason, line_blocker
from condition_sources import DeliveryRefused
from mentor_variants import MentorVariant
from patron_synergy_combat import inspire_attack_upgrade
from patron_synergy_heal import for_cast
from resource_costs import gate_pool
from session_data import CombatParticipant, SessionData

if TYPE_CHECKING:
    from declarations import Declaration
    from spell_casting import CastResult


def condition_ability(resolved: DeclaredAbility | None) -> DeclaredAbility | None:
    """The non-spell, condition-applying declared ability, or None.

    The in-combat ABILITY path resolves spells by default (via _gate_spell / _resolve_cast); a
    non-spell ability that PRODUCES a condition (M4.8 story-005, e.g. bard_inspire) takes the
    dedicated ability-condition path instead. An ability is on that path iff it carries
    ``applies_condition`` AND has no ``spell_id`` — a spell-backed condition ability keeps the
    spell path, where story-004's producer block already applies it (assumption 07d1a208794b).
    Returns None for an unknown action or any spell/non-condition ability."""
    if resolved is None:
        return None
    ability, _variant = resolved
    if ability.applies_condition is not None and ability.spell_id is None:
        return resolved
    return None


def _gate_ability_condition(
    player: dict,
    ability: "abilities.Ability",
    variant: MentorVariant | None = None,
) -> None:
    """Declare-time fail-loud gate for a non-spell condition ability (M4.8 story-005): validate the
    ability's Stamina/Focus with NO writes, mirroring _gate_deescalation / _gate_spell so a bad
    declaration never rolls back a phase that already resolved other actors. resource_costs.gate_pool
    is the sole Focus/Stamina gate; the deduct happens in _resolve_ability_condition_packet."""
    cost = variant.cost if variant is not None else ability.cost
    gate_pool(player, "stamina", cost.stamina, label=ability.name)
    gate_pool(player, "focus", cost.focus, label=ability.name)


async def _deduct_ability_cost(player_id, ability, variant, *, persistence, queries, conn) -> None:
    cost = variant.cost if variant is not None else ability.cost
    if not (cost.stamina or cost.focus):
        return
    # Earlier packets can restore resources after this actor's prevalidation.
    player = await queries.get_player(player_id, conn=conn, for_update=True)
    if player is None:
        raise ToolError(f"Unknown player: {player_id}")
    new_stamina = gate_pool(player, "stamina", cost.stamina, label=ability.name)
    new_focus = gate_pool(player, "focus", cost.focus, label=ability.name)
    await persistence.update_player_resources(player_id, stamina=new_stamina, focus=new_focus, conn=conn)


async def _resolve_ability_condition_packet(
    session: SessionData,
    attacker: CombatParticipant,
    decl: "Declaration",
    resolved: DeclaredAbility,
    *,
    state,
    conn,
    player: dict | None,
    persistence=ability_persistence,
    queries=db_queries,
    progress=None,
) -> dict:
    """Resolve a non-spell condition-applying ABILITY in combat (M4.8 story-005, e.g. bard_inspire).

    Resolve the TARGET participant FIRST: self-target (no target_id) is the caster (always present);
    a given target_id that's not on the working state, or one already fallen, WASTES the declaration
    (resolved:False) WITHOUT deducting — you can't buff a target that left or a corpse, and a wasted
    declaration must never burn the ability's Stamina/Focus (mirrors the attack path's wasted-target
    guards). Only once a live target is confirmed do we deduct the cost (pre-gated at declare time via
    _gate_ability_condition) and land applies_condition on it via the shared helper — the mutation
    rides the phase save_combat_state (no extra write)."""
    if state is None or player is None:
        return {"actor_id": attacker.id, "resolved": False, "reason": "no active combat or player"}

    combat_voice_rules.guard_declaration(state, attacker, decl)
    ability, variant = resolved

    # applies_condition is non-None on this path (condition_ability selected it). The source is the
    # base ability id, which differs from decl.action when a mentor variant was declared.
    cond_type = ability.applies_condition
    upgrade = False
    if cond_type == "inspired":
        upgrade = inspire_attack_upgrade(player)
        eligible = condition_voice_rules.spoken_buff_targets(
            cond_type, state, attacker.id, decl.target_ids or [decl.target_id or attacker.id]
        )
        decl = replace(
            decl, target_ids=eligible if decl.target_ids else [], target_id=None if decl.target_ids else eligible[0]
        )

    # Multi-target (M4.8 story-016, e.g. bard_mass_inspire): the cap was validated at the
    # declare-gate (spells.normalize_target_list). Deduct once, land on EACH live ally, and voice
    # the landed set (condition_targets) — mirroring the multi-target spell path. A target gone by
    # resolve time is dropped (partial landing); an all-off-state list lands nothing but still
    # spends the cost (the spell-path convention — the declaration committed to the action).
    if decl.target_ids:
        await _deduct_ability_cost(attacker.id, ability, variant, persistence=persistence, queries=queries, conn=conn)
        summary = {
            "actor_id": attacker.id,
            "resolved": True,
            "declaration_type": str(decl.type),
            "action": ability.id,
        }
        if cond_type is not None:
            voiced = land_condition_on_participants(
                state, attacker, decl, cond_type, source=ability.id, packet=summary, inspire_attack_upgrade=upgrade
            )
            if voiced:
                summary["condition_applied"] = cond_type
                summary["condition_targets"] = voiced
        return _with_variant(summary, variant)

    # Single-target (story-005): a given target_id that's not on the working state, or already
    # fallen, WASTES the declaration (resolved:False) WITHOUT deducting — you can't buff a target
    # that left or a corpse, and a wasted declaration must never burn the cost.
    target, waste = _resolve_condition_target(state, attacker, decl)
    if waste is not None:
        return waste
    assert target is not None

    steps = progress.steps if progress is not None else {}
    if not steps.get("cost_paid"):
        if wall := line_blocker(state, attacker.id, target.id):
            return {"actor_id": attacker.id, "resolved": False, "reason": blocked_reason(wall)}
        await _deduct_ability_cost(attacker.id, ability, variant, persistence=persistence, queries=queries, conn=conn)
        steps["cost_paid"] = True

    if combat_ability_save.requires_hostile_target(ability):
        summary = await combat_ability_save.resolve_hostile_condition(
            session,
            state,
            attacker,
            target,
            decl,
            ability,
            _land_condition_on_one,
            progress=progress,
        )
        return _with_variant(summary, variant)

    summary = {
        "actor_id": attacker.id,
        "resolved": True,
        "declaration_type": str(decl.type),
        "action": ability.id,
    }
    if cond_type is not None and land_condition_on_participant(
        state, attacker, decl, cond_type, source=ability.id, packet=summary, inspire_attack_upgrade=upgrade
    ):
        summary["condition_applied"] = cond_type
    return _with_variant(summary, variant)


def _with_variant(summary: dict, variant: MentorVariant | None) -> dict:
    if variant is not None:
        summary["variant_id"] = variant.id
        summary["cultural_attribution"] = variant.cultural_attribution
    return summary


def _resolve_condition_target(
    state, attacker: CombatParticipant, decl: "Declaration", *, allow_self: bool = True, damage: bool = False
):
    """Resolve the single target of a condition-applying declaration.

    Returns ``(target, None)`` for a live target, or ``(None, waste_summary)`` when the target is
    gone / disallowed — a wasted declaration must never apply the condition or
    deduct a cost. ``allow_self`` controls the ``target_id is None`` case: True (default) falls back
    to the caster (a player self-buff); False WASTES it instead — a hostile inflict must never
    self-target (an ABILITY-declared enemy condition action, which skips ATTACK's target_id
    validation, would otherwise make the enemy inflict on ITSELF). Shared by the player ability-
    condition path and the enemy condition-infliction path so the wasted-target contract lives once.
    ``damage`` permits nonterminal Fallen allies only on the damaging save path."""
    target = attacker if decl.target_id is None else state.get_participant(decl.target_id)
    # allow_self=False wastes ANY self-target: the None fallback OR an explicit target_id equal to
    # the attacker's own id — a hostile inflict must never land on its own caster.
    if not allow_self and (decl.target_id is None or (target is not None and target.id == attacker.id)):
        return None, {
            "actor_id": attacker.id,
            "resolved": False,
            "declaration_type": str(decl.type),
            "reason": "condition action requires a non-self target_id",
        }
    if target is None:
        return None, {
            "actor_id": attacker.id,
            "resolved": False,
            "declaration_type": str(decl.type),
            "reason": f"target '{decl.target_id}' not found",
        }
    if damage_target_unavailable(target) if damage else target.is_fallen:
        return None, {
            "actor_id": attacker.id,
            "resolved": False,
            "declaration_type": str(decl.type),
            "reason": f"{target.name} already fell",
        }
    return target, None


@dataclass
class AbilityCastOutcome:
    """Side-channel carrying the in-loop ABILITY casts' ``CastResult``s back to the phase loop.

    Each party member may declare one ability per phase (M14 story-004), so results are keyed by the
    caster's participant id (== player_id). The loop reads ``results`` post-commit to seed each
    member's WRAP resonance, flush their deferred client events, and push per-member HUD state — all
    of which must happen after the phase tx commits (story-007). ``results`` stays empty when no
    ability resolved. Concentration is synced IN-LOOP by ``_resolve_ability_packet`` (not here)."""

    results: dict[str, "CastResult"] = field(default_factory=dict)


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
    damage_deps=None,
    progress=None,
) -> dict:
    """Cast once, then land spell damage and conditions on effective recipients."""
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

    import choir_encounter
    import still_encounter

    still_encounter.guard_declaration(state, attacker.id, decl)
    choir_encounter.guard_declaration(state, attacker.id, decl)
    caster = session.member_state(attacker.id)
    combat_voice_rules.guard_declaration(state, attacker, decl)
    import spells
    from choir_reaction import effective_declaration
    from combat_spell_recipients import select

    spell = spells.get_spell(decl.action)
    steps = progress.steps if progress is not None else {}
    shield = progress.scope("shield") if progress is not None else None
    deliveries = None
    recipient_profile = spell.combat_damage and spell.combat_damage.get("recipients")
    if (
        not recipient_profile
        and "cast_packet" not in steps
        and (wall := line_blocker(state, attacker.id, decl.target_id))
    ):
        return {"actor_id": attacker.id, "resolved": False, "reason": blocked_reason(wall)}
    if recipient_profile:
        # Area recipients are frozen once, then each distinct recipient may redirect the spell (the
        # Choir's shield). A Zhael-held redirect save resumes here without re-selecting or re-rolling.
        selected = steps.get("selected")
        if selected is None:
            try:
                selected = select(state, attacker, decl, spell)
            except DeliveryRefused as e:
                return {"actor_id": attacker.id, "resolved": False, "reason": str(e)}
            if progress is not None:
                steps["selected"] = selected
        redirects = steps.setdefault("redirects", {})
        for target_id in dict.fromkeys(d["target_id"] for d in selected):
            if target_id in redirects:
                continue
            redirected = await effective_declaration(
                session,
                state,
                attacker,
                replace(decl, target_id=target_id, target_ids=None),
                progress=shield.scope(target_id) if shield is not None else None,
            )
            if redirected is None:
                return {}
            redirects[target_id] = redirected.target_id
        deliveries = [{**d, "target_id": redirects[d["target_id"]]} for d in selected]
    elif spell.heal is None:
        decl = await effective_declaration(session, state, attacker, decl, progress=shield)
        if decl is None:
            return {}
    landing_intent, deliveries, interception = architect_reaction.spell_targets(
        state, attacker, decl, spell, deliveries, steps
    )
    cast_packet = steps.get("cast_packet")
    if cast_packet is None:
        heal = spell.heal
        recipients = []
        if heal is not None:
            try:
                recipients = combat_spell_heal.combat_recipients(state, attacker, decl, spell, heal)
            except ValueError as e:
                return {"actor_id": attacker.id, "resolved": False, "reason": str(e)}
        result = await cast_resolver._resolve_cast(
            session,
            decl.action,
            conn=conn,
            caster=caster,
            player=player,
            combat_state=state,
            target_id=decl.target_id,
            target_ids=decl.target_ids,
            suppress_resonance_changed=True,
        )
        cast_outcome.results[attacker.id] = result
        if result.new_resonance is not None:
            combat_hollow_resonance.stage_total(state, attacker.id, result.new_resonance)
        # Later damage in this transaction must check the spell the caster just started concentrating on.
        if result.concentration_spell_id is not spell_casting._UNCHANGED:
            caster.concentration.spell_id = cast("str | None", result.concentration_spell_id)
        cast_packet = result.packet
        if heal is not None:
            if player is None:
                raise RuntimeError(f"Missing locked player row for healing caster {attacker.id}")
            cast_packet["healing_results"] = await combat_spell_heal.land(
                heal,
                attacker,
                recipients,
                caster_row=player,
                synergy=for_cast(
                    player,
                    terrain=result.terrain,
                    first_stay=result.first_stay,
                    facts=state.encounter_facts,
                    round_number=state.round_number,
                ),
                packet=cast_packet,
                conn=conn,
            )
        # Veilrender Absorb Magic heals once per cast, so its landing is frozen with the cast packet.
        if deliveries is not None:
            effective_ids = list(dict.fromkeys(d["target_id"] for d in deliveries))
            landing = (
                combat_veilrender.absorb_spell(
                    state, attacker, replace(decl, target_id=None, target_ids=effective_ids), cast_packet
                )
                if effective_ids
                else None
            )
        else:
            landing = (
                combat_veilrender.absorb_spell(state, attacker, landing_intent, cast_packet)
                if landing_intent is not None
                else None
            )
        if interception is not None and landing is None:
            cast_packet["narration_cue"] = cast_packet["effect"] = interception["cue"]
            cast_packet.pop("damage_dice", None)
            cast_packet.pop("condition_applied", None)
        steps["cast_packet"] = cast_packet
        steps["landing"] = (
            None if landing is None else {"target_id": landing.target_id, "target_ids": landing.target_ids}
        )
    landing = None if steps["landing"] is None else replace(decl, **steps["landing"])
    if deliveries is not None:
        absorbed = {receipt["target_id"] for receipt in cast_packet.get("absorbed", [])}
        deliveries = [d for d in deliveries if d["target_id"] not in absorbed]
    if deliveries is not None or landing is not None:
        await combat_spell_damage.land(
            session,
            state,
            attacker,
            landing or decl,
            cast_packet,
            conn=conn,
            deliveries=deliveries,
            progress=progress.scope("spell_damage") if progress is not None else None,
            **(damage_deps or {}),
        )
        if progress is not None and progress.paused:
            return (
                {"actor_id": attacker.id, "resolved": False, "reactive_architecture": interception}
                if interception is not None
                else {}
            )
    # Beneficial-condition PRODUCER (M4.8 story-004), in-combat half: land the produced condition on the
    # recipients that remain after Absorb Magic. The mutation rides this phase's save_combat_state.
    cond_type = cast_packet.get("condition_applied")
    if cond_type and landing is not None:
        voiced = land_condition_on_participants(
            state, attacker, landing, cond_type, source=landing.action, packet=cast_packet
        )
        if voiced:
            cast_packet["condition_targets"] = voiced
        else:
            cast_packet.pop("condition_applied", None)
    summary = {
        "actor_id": attacker.id,
        "resolved": True,
        "declaration_type": str(decl.type),
        "action": decl.action,
        "cast": cast_packet,
    }
    if interception is not None:
        summary["reactive_architecture"] = interception
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
    riders = combat_enhancers.declaration_riders(attacker.enhancers, decl)
    if riders:
        summary["riders"] = riders
    return summary
