"""Resolve the Architect's automatic encounter save override."""

from collections.abc import Iterable
from dataclasses import replace

import architect_encounter
import combat_recharge
from check_resolution_save import SavingThrowResult
from combat_condition_landing import can_land_condition
from combat_participant import CombatParticipant
from combat_state import CombatState


def finalize_save(
    state: CombatState,
    target: CombatParticipant,
    result: SavingThrowResult,
    *,
    failed_conditions: Iterable[str] = (),
    failed_damage: int = 0,
) -> SavingThrowResult:
    if (
        target.creature_id != architect_encounter.CREATURE_ID
        or target.hp_current <= 0
        or target.is_fallen
        or target.is_dead
        or result.success
    ):
        return result
    action = combat_recharge.LEGENDARY_RESISTANCE
    if not combat_recharge.available(target, action):
        return result
    # Decision (3) spends on a failure that would APPLY a condition; one already held is not applied.
    held = {condition["type"] for condition in target.conditions}
    if 4 * failed_damage < target.hp_current and not any(
        condition not in held and can_land_condition(state, target, condition) for condition in failed_conditions
    ):
        return result
    combat_recharge.spend(target, action, state.round_number)
    return replace(
        result,
        success=True,
        effect_applied=None,
        narrative_hint=f"{target.name} succeeds using {action['name']}.",
        success_override=action["name"],
    )


def override_fields(result: SavingThrowResult) -> dict[str, str]:
    override = getattr(result, "success_override", None)
    return {"success_override": override} if override is not None else {}
