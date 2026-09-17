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


def gate_hostile_target(state: "CombatState", decl: "Declaration", ability: "Ability") -> None:
    if ability.save is None:
        return
    target = state.get_participant(decl.target_id) if decl.target_id is not None else None
    if target is None or target.is_ally or target.is_fallen:
        raise ToolError(f"{ability.name} requires a standing foe.")


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
    elif land_condition(state, target.id, attacker, cond_type, ability.id):
        summary["condition_inflicted"] = cond_type
    else:
        summary["condition_immune"] = cond_type
    return summary
