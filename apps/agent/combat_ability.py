"""Resolve non-spell combat abilities that apply conditions."""

from dataclasses import replace
from functools import partial
from typing import TYPE_CHECKING

from livekit.agents.llm import ToolError

import abilities
import ability_persistence
import combat_ability_save
import combat_spell_heal
import combat_voice_rules
import combat_yield
import condition_voice_rules
import db_queries
import patron_synergy_heal
from combat_ability_cast import AbilityCastOutcome as AbilityCastOutcome
from combat_ability_cast import _attach_riders as _attach_riders
from combat_ability_cast import _resolve_ability_packet as _resolve_ability_packet
from combat_ability_gate import WAR_CRIES, DeclaredAbility
from combat_condition_landing import (
    _land_condition_on_one,
    land_condition_on_participant,
    land_condition_on_participants,
)
from combat_condition_target import _resolve_condition_target
from combat_structures import blocked_reason, line_blocker
from mentor_variants import MentorVariant
from patron_synergy_combat import inspire_attack_upgrade
from resource_costs import gate_pool
from session_data import CombatParticipant, SessionData

if TYPE_CHECKING:
    from declarations import Declaration


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
    """Settle a condition ability or Inspire heal after delivery and target checks."""
    if state is None or player is None:
        return {"actor_id": attacker.id, "resolved": False, "reason": "no active combat or player"}

    ability, variant = resolved
    if ability.id in WAR_CRIES:
        summary = await combat_ability_save.resolve_war_cry(
            session,
            state,
            attacker,
            decl,
            ability,
            _land_condition_on_one,
            pay=partial(
                _deduct_ability_cost, attacker.id, ability, variant, persistence=persistence, queries=queries, conn=conn
            ),
            progress=progress.scope(ability.id) if progress is not None else None,
        )
        if summary.get("condition_results"):
            summary.update(combat_yield.end(attacker))
        return _with_variant(summary, variant) if summary else {}

    combat_voice_rules.guard_declaration(state, attacker, decl)

    # applies_condition is non-None on this path (condition_ability selected it). The source is the
    # base ability id, which differs from decl.action when a mentor variant was declared.
    cond_type = ability.applies_condition
    heal_mode = decl.action == patron_synergy_heal.INSPIRE_HEAL
    upgrade = False
    if cond_type == "inspired":
        upgrade = not heal_mode and inspire_attack_upgrade(player)
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
    if heal_mode and not target.is_ally:
        return {"actor_id": attacker.id, "resolved": False, "reason": "Inspire healing requires an ally."}

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
        if summary.get("resolved"):
            summary.update(combat_yield.end(attacker))
        return _with_variant(summary, variant)

    summary = {
        "actor_id": attacker.id,
        "resolved": True,
        "declaration_type": str(decl.type),
        "action": ability.id,
    }
    if heal_mode:
        profile = patron_synergy_heal.inspire_heal()
        results = await combat_spell_heal.land(
            profile, attacker, [target], caster_row=player, synergy=None, packet=summary, conn=conn
        )
        combat_spell_heal.inspire_receipt(summary, profile, results)
        return summary
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


def _find_action(participant, action_name) -> dict | None:
    """Find the named action in a participant's action_pool (case-insensitive)."""
    if not action_name:
        return None
    wanted = str(action_name).lower()
    for a in participant.action_pool:
        if a.get("name", "").lower() == wanted:
            return a
    return None
