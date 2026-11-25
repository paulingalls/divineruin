"""Targeting and resolution for hostile player condition abilities."""

from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING

from livekit.agents.llm import ToolError

import check_resolution_save
import rules_engine
from combat_fate_rolls import packet_save
from combat_legendary_resistance import finalize_save, override_fields

if TYPE_CHECKING:
    from abilities import Ability
    from declarations import Declaration
    from session_data import CombatParticipant, CombatState


BENEFICIAL_CONDITIONS = frozenset({"blessed", "shielded", "enraged", "inspired", "precise_strike"})


def requires_hostile_target(ability: "Ability") -> bool:
    return ability.save is not None or (
        ability.applies_condition is not None and ability.applies_condition not in BENEFICIAL_CONDITIONS
    )


def gate_hostile_condition_targets(state: "CombatState", decl: "Declaration", condition: str, action_name: str) -> None:
    if condition in BENEFICIAL_CONDITIONS:
        return
    target_ids = decl.target_ids or [decl.target_id]
    for target_id in target_ids:
        target = state.get_participant(target_id) if target_id is not None else None
        if target is None or target.is_ally or target.is_fallen:
            raise ToolError(f"{action_name} requires a standing foe.")


def gate_hostile_target(state: "CombatState", decl: "Declaration", ability: "Ability") -> None:
    assert ability.applies_condition is not None
    gate_hostile_condition_targets(state, decl, ability.applies_condition, ability.name)


def player_ability_dc(attacker: "CombatParticipant", attribute: str) -> int:
    return (
        8
        + rules_engine.proficiency_bonus(attacker.level)
        + rules_engine.attribute_modifier(attacker.attributes[attribute])
    )


async def resolve_hostile_condition(
    session,
    state: "CombatState",
    attacker: "CombatParticipant",
    target: "CombatParticipant",
    decl: "Declaration",
    ability: "Ability",
    land_condition: Callable[..., bool],
    *,
    progress=None,
) -> dict:
    cond_type = ability.applies_condition
    assert cond_type is not None
    summary = {
        "actor_id": attacker.id,
        "resolved": True,
        "declaration_type": str(decl.type),
        "action": ability.id,
        "target": target.name,
    }
    if ability.save is not None:
        assert ability.dc_attribute is not None
        dc = player_ability_dc(attacker, ability.dc_attribute)
        result = await packet_save(
            progress,
            session,
            target.id,
            cond_type,
            partial(
                check_resolution_save.roll_participant_save,
                target,
                ability.save,
                dc,
                cond_type,
                originating_participant_id=attacker.id,
                combat_state=state,
            ),
        )
        if result is None:
            return {}
        result = finalize_save(state, target, result, failed_conditions=(cond_type,))
        summary.update(override_fields(result), save_success=result.success)
        if result.success:
            summary["condition_resisted"] = cond_type
            return summary
    duration = 1 if ability.id == "rogue_dirty_trick" else None
    if land_condition(state, target.id, attacker, cond_type, ability.id, duration=duration, packet=summary):
        summary["condition_inflicted"] = cond_type
    else:
        summary["condition_immune"] = cond_type
    return summary
