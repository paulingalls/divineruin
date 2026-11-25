"""Settle damage and resume held saves without rolling the original blow again."""

from functools import partial

import check_resolution_attack
import concentration_break
import db_mutations
import db_queries
from combat_damage_results import AutomaticDamageResult, SaveDamageResult, freeze_blow, thaw_blow
from combat_enemy_active import apply_prepared_hit, critical_save_rider, land_critical_save, roll_critical_save
from combat_fate_rolls import packet_save
from session_data import SessionData


async def apply_attack_result(
    session: SessionData,
    attacker,
    action: dict,
    target,
    attack_result: check_resolution_attack.AttackResult | SaveDamageResult | AutomaticDamageResult | None,
    effective_ac: int,
    *,
    shield_reaction: str | None = None,
    mutations=db_mutations,
    queries=db_queries,
    concentration_break_mod=concentration_break,
    combat_state=None,
    conn=None,
    sink=None,
    publish_roll: bool = True,
    progress=None,
) -> dict:
    from combat_damage import _apply_damage

    if progress is None:
        assert attack_result is not None
        direct = await _apply_damage(
            session,
            attacker,
            action,
            target,
            attack_result,
            effective_ac,
            shield_reaction=shield_reaction,
            mutations=mutations,
            queries=queries,
            concentration_break_mod=concentration_break_mod,
            combat_state=combat_state,
            conn=conn,
            sink=sink,
            publish_roll=publish_roll,
        )
        assert direct is not None  # only a fortitude_progress hold pauses
        return direct

    receipt = progress.steps.get("damage_receipt")
    if receipt is not None and "pending" in receipt:
        # A held Unholy Fortitude save paused before HP changed; land the same blow now.
        action, attack_result, effective_ac = thaw_blow(receipt["pending"])
        receipt = None
    if receipt is None:
        assert attack_result is not None
        response = await _apply_damage(
            session,
            attacker,
            action,
            target,
            attack_result,
            effective_ac,
            shield_reaction=shield_reaction,
            mutations=mutations,
            queries=queries,
            concentration_break_mod=concentration_break_mod,
            combat_state=combat_state,
            conn=conn,
            sink=sink,
            publish_roll=publish_roll,
            defer_concentration=True,
            fortitude_progress=progress.scope("fortitude"),
        )
        if response is None:
            # Callers treat a present receipt as "already rolled" and resume without re-rolling.
            progress.steps["damage_receipt"] = {"pending": freeze_blow(action, attack_result, effective_ac)}
            return {}
        if "consumed_conditions" in response:
            response["consumed_conditions"] = list(response["consumed_conditions"])
        receipt = {"response": response, "automatic": isinstance(attack_result, AutomaticDamageResult)}
        progress.steps["damage_receipt"] = receipt
    response = receipt["response"]
    if target.type == "player" and not receipt.get("concentration_settled"):
        response["concentration_broken"] = await concentration_break_mod.break_concentration_on_damage(
            session,
            response["damage"],
            incapacitated=target.hp_current <= 0,
            damaged_player_id=target.id,
            combat_state=combat_state,
            conn=conn,
            progress=progress.scope("concentration"),
            receipt=response,
        )
        if progress.paused:
            return {}
        receipt["concentration_settled"] = True
    if combat_state is not None and not receipt["automatic"]:
        rider = critical_save_rider(action, response)
        save = None
        if rider is not None:
            # Fate's Thread reaches the target's on-crit save; it resolves before any rider lands.
            save = await packet_save(
                progress.scope("critical_save"),
                session,
                target.id,
                rider["applies_condition"],
                partial(roll_critical_save, combat_state, attacker, target, rider),
                state=combat_state,
            )
            if save is None:
                return {}
        apply_prepared_hit(combat_state, attacker, target, action, response)
        if save is not None:
            land_critical_save(combat_state, attacker, target, action, response, rider, save)
    del progress.steps["damage_receipt"]
    return response
