"""Shared helpers for combat tool modules."""

import logging
from inspect import getattr_static

from livekit.agents.llm import ToolError

import check_resolution_attack
import combat_grapple
import combat_resolution
import combat_wrongdoing
import combat_yield
import concentration_break
import conditions
import db_mutations
import db_queries
import reaction_windows
import thyra_seasons
from combat_action_availability import action_summary
from combat_attack_roll import deserialize_roll as deserialize_roll
from combat_attack_roll import roll_attack
from combat_attack_roll import serialize_roll as serialize_roll
from combat_condition_landing import _land_condition_on_one
from combat_damage import apply_attack_result
from condition_restrictions import cannot_act
from equipment_rules import resolve_weapon_profile, with_weapon_magic
from patron_synergy_combat import VeiledStrike, attack_player, witness_defense
from session_data import CombatParticipant, CombatState, SessionData

logger = logging.getLogger("divineruin.tools")


def _participant_summary(p: CombatParticipant) -> dict:
    """Serialize a participant for LLM response (no internal state like HP numbers)."""
    return {
        "id": p.id,
        "name": p.name,
        "yielded": p.yielded,
        "type": p.type,
        "initiative": p.initiative,
        "hp_status": combat_resolution.hp_threshold_status(p.hp_current, p.hp_max),
        "ac": p.ac,
        "is_fallen": p.is_fallen,
        "cannot_act": list(cannot_act(p.conditions)),
        "prone": conditions.has_condition(p.conditions, "prone"),
        "grappled_by": combat_grapple.grappler_id(p.conditions),
        "creature_id": p.creature_id,
        "catalog_narration": p.catalog_narration,
        "catalog_audio": p.catalog_audio,
        "deferred_effects": p.deferred_effects,
        **action_summary(p),
    }


def _participant_roster(participants: list[CombatParticipant]) -> list[dict]:
    return [_participant_summary(participant) for participant in participants]


def _require_combat(session: SessionData) -> CombatState:
    """Return the combat state, or raise ToolError if not in combat (ADR 0002)."""
    if session.combat_state is None:
        raise ToolError("Not in combat.")
    return session.combat_state


async def _resolve_attack_packet(
    session: SessionData,
    attacker,
    action: dict,
    target,
    *,
    target_ac_bonus: int = 0,
    shield_reaction: str | None = None,
    damage_target: CombatParticipant | None = None,
    grapple_blocked: bool = False,
    enemies_remaining: int | None = None,
    is_first_attack_of_combat: bool = False,
    mutations=db_mutations,
    queries=db_queries,
    resolver=check_resolution_attack,
    concentration_break_mod=concentration_break,
    combat_state=None,
    conn=None,
    sink=None,
    publish_roll: bool = True,
    progress=None,
    weapon_attack: bool = True,
    veiled_strike: VeiledStrike | None = None,
) -> dict:
    if progress is not None and "damage_receipt" in progress.steps:
        attack_result, effective_ac = None, target.ac
    else:
        player = await attack_player(attacker, queries=queries, conn=conn)
        defender = await attack_player(target, queries=queries, conn=conn) if combat_state is not None else None
        profile = await resolve_weapon_profile(
            attacker.type, action, player=player, weapon_attack=weapon_attack, conn=conn
        )
        action = with_weapon_magic(action, profile)
        attack_result, effective_ac = roll_attack(
            attacker,
            action,
            target,
            valdris_ac_bonus=await witness_defense(defender, combat_state, attacker, queries=queries, conn=conn),
            target_ac_bonus=target_ac_bonus,
            enemies_remaining=enemies_remaining,
            is_first_attack_of_combat=is_first_attack_of_combat,
            resolver=resolver,
            combat_state=combat_state,
            weapon_attack=weapon_attack,
            weapon_profile=profile,
            veiled_strike=veiled_strike,
            player=player,
            defender=defender,
            season=await thyra_seasons.season_for(player, conn=conn),
            mortaen_ac_override=getattr_static(resolver, "mortaen_ac_bonus", None),
            orenthel_ac_override=getattr_static(resolver, "orenthel_ac_bonus", None),
        )
    return await apply_rolled_attack(
        session,
        attacker,
        action,
        target,
        attack_result,
        effective_ac,
        shield_reaction=shield_reaction,
        damage_target=damage_target,
        grapple_blocked=grapple_blocked,
        mutations=mutations,
        queries=queries,
        concentration_break_mod=concentration_break_mod,
        combat_state=combat_state,
        conn=conn,
        sink=sink,
        publish_roll=publish_roll,
        progress=progress,
    )


async def apply_rolled_attack(
    session,
    attacker,
    action,
    target,
    attack_result,
    effective_ac,
    *,
    shield_reaction=None,
    damage_target: CombatParticipant | None = None,
    grapple_blocked=False,
    mutations=db_mutations,
    queries=db_queries,
    concentration_break_mod=concentration_break,
    combat_state=None,
    conn=None,
    sink=None,
    publish_roll=True,
    progress=None,
):
    steps = progress.steps if progress is not None else {}
    if attack_result is not None:
        combat_wrongdoing.record_attack(combat_state, attacker, target)
        if not target.is_ally and (receipt := combat_yield.end(attacker)):
            steps["yield_receipt"] = receipt
    summary = await apply_attack_result(
        session,
        attacker,
        action,
        target,
        attack_result,
        effective_ac,
        shield_reaction=shield_reaction,
        damage_target=damage_target,
        mutations=mutations,
        queries=queries,
        concentration_break_mod=concentration_break_mod,
        combat_state=combat_state,
        conn=conn,
        sink=sink,
        publish_roll=publish_roll,
        progress=progress,
    )
    summary.update(steps.get("yield_receipt", {}))
    if (
        summary.get("hit")
        and reaction_windows.GRAPPLE_PROPERTY in action.get("properties", [])
        and not grapple_blocked
        and combat_state is not None
        and not target.is_fallen
    ):
        if conditions.has_condition(target.conditions, "grappled"):
            summary["grapple_held"] = True
        elif _land_condition_on_one(combat_state, target.id, attacker, "grappled", source=attacker.id, packet=summary):
            summary["condition_inflicted"] = "grappled"
        else:
            summary["condition_immune"] = "grappled"
            summary["condition_immunity_source"] = target.condition_immunities["grappled"]
    return summary
