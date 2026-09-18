"""Hostile saving-throw mechanics for player condition abilities."""

from collections.abc import Callable
from typing import TYPE_CHECKING

from livekit.agents.llm import ToolError

import check_resolution_save
import rules_engine

if TYPE_CHECKING:
    from abilities import Ability
    from declarations import Declaration
    from session_data import CombatParticipant, CombatState


BENEFICIAL_CONDITIONS = frozenset({"blessed", "shielded", "enraged", "inspired"})


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


def resolve_hostile_condition(
    state: "CombatState",
    attacker: "CombatParticipant",
    target: "CombatParticipant",
    decl: "Declaration",
    ability: "Ability",
    land_condition: Callable[..., bool],
) -> dict:
    cond_type = ability.applies_condition
    assert cond_type is not None
    assert ability.save is not None
    assert ability.dc_attribute is not None
    dc = (
        8
        + rules_engine.proficiency_bonus(attacker.level)
        + rules_engine.attribute_modifier(attacker.attributes[ability.dc_attribute])
    )
    result = check_resolution_save.roll_participant_save(target, ability.save, dc, cond_type)
    summary = {
        "actor_id": attacker.id,
        "resolved": True,
        "declaration_type": str(decl.type),
        "action": ability.id,
        "target": target.name,
    }
    if result.success:
        summary["condition_resisted"] = cond_type
    elif land_condition(state, target.id, attacker, cond_type, ability.id, packet=summary):
        summary["condition_inflicted"] = cond_type
    else:
        summary["condition_immune"] = cond_type
    return summary
