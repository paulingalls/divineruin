"""Settle damage and resume held saves without rolling the original blow again."""

from collections.abc import Awaitable, Callable
from functools import partial

import check_resolution_attack
import concentration_break
import db_mutations
import db_queries
from combat_damage_results import AutomaticDamageResult, SaveDamageResult, freeze_blow, thaw_blow
from combat_enemy_active import apply_prepared_hit, critical_save_rider, land_critical_save, roll_critical_save
from combat_fate_rolls import packet_save
from combat_order_riders import COORDINATED_ASSAULT_NAME, FirstHit
from dice import roll as dice_roll
from session_data import CombatParticipant, CombatState, SessionData


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

    land_damage = partial(
        _apply_damage,
        session,
        shield_reaction=shield_reaction,
        publish_roll=publish_roll,
        mutations=mutations,
        queries=queries,
        concentration_break_mod=concentration_break_mod,
        combat_state=combat_state,
        conn=conn,
        sink=sink,
    )
    land_deferred = partial(
        apply_attack_result,
        session,
        publish_roll=False,
        mutations=mutations,
        queries=queries,
        concentration_break_mod=concentration_break_mod,
        combat_state=combat_state,
        conn=conn,
        sink=sink,
    )
    if progress is None:
        assert attack_result is not None
        direct = await land_damage(attacker, action, target, attack_result, effective_ac)
        assert direct is not None  # only a fortitude_progress hold pauses
        if (first_hit := _pincer_first_hit(attack_result)) is not None:
            await _settle_pincer(combat_state, attacker, target, direct, first_hit, land_deferred, None)
        return direct

    receipt = progress.steps.get("damage_receipt")
    if receipt is not None and "pending" in receipt:
        # A held Unholy Fortitude save paused before HP changed; land the same blow now.
        action, attack_result, effective_ac = thaw_blow(receipt["pending"])
        receipt = None
    if receipt is None:
        assert attack_result is not None
        response = await land_damage(
            attacker,
            action,
            target,
            attack_result,
            effective_ac,
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
        if (first_hit := _pincer_first_hit(attack_result)) is not None:
            receipt["pincer_first_hit"] = first_hit
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
    if combat_state is not None and not receipt["automatic"] and not receipt.get("consequences_settled"):
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
        receipt["consequences_settled"] = True
    if (first_hit := receipt.get("pincer_first_hit")) is not None:
        await _settle_pincer(
            combat_state, attacker, target, response, first_hit, land_deferred, progress.scope("pincer")
        )
        if progress.paused:
            return {}
    del progress.steps["damage_receipt"]
    return response


def _pincer_first_hit(
    result: check_resolution_attack.AttackResult | SaveDamageResult | AutomaticDamageResult,
) -> FirstHit | None:
    if isinstance(result, check_resolution_attack.AttackResult) and result.pincer_dice is not None:
        assert result.coordinated_rider is not None and result.coordinated_rider["first_hit"] is not None
        return result.coordinated_rider["first_hit"]
    return None


async def _settle_pincer(
    state: CombatState | None,
    attacker: CombatParticipant,
    target: CombatParticipant,
    response: dict,
    first_hit: FirstHit,
    land: Callable[..., Awaitable[dict]],
    progress,
) -> None:
    assert state is not None
    coordinated = response["coordinated_assault"]
    second = dict(
        ally_id=attacker.id,
        dice=coordinated["dice"],
        raw_damage=coordinated["raw_damage"],
        landing={key: response[key] for key in ("damage", "damage_type", "target_hp_status", "target_fallen")},
    )
    first: dict = dict(ally_id=first_hit["ally_id"], dice="1d6")
    if target.is_fallen:
        first["skipped"] = "target_fallen"
    else:
        source = state.get_participant(first_hit["ally_id"])
        assert source is not None
        steps = progress.steps if progress is not None else {}
        if "raw_damage" not in steps:
            steps["raw_damage"] = dice_roll("1d6").total
        raw_damage = steps["raw_damage"]
        delivery = dict(
            name=COORDINATED_ASSAULT_NAME,
            magical=first_hit["magical"],
            spell_source=first_hit["spell_source"],
        )
        result = AutomaticDamageResult(raw_damage, first_hit["damage_type"], COORDINATED_ASSAULT_NAME)
        landing = await land(source, delivery, target, result, target.ac, progress=progress)
        if progress is not None and progress.paused:
            return
        first.update(raw_damage=raw_damage, landing=landing)
        for key in ("target_hp_status", "target_fallen", "target_rose_hollowed"):
            response[key] = landing[key]
    del coordinated["dice"], coordinated["raw_damage"]
    coordinated["pincer"] = dict(target_id=target.id, landings=[second, first])
