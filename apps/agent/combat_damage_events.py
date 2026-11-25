"""Record the session event for a landed damage packet."""

from check_resolution_attack import AttackResult
from combat_damage_results import AutomaticDamageResult, SaveDamageResult
from combat_participant import CombatParticipant
from session_data import SessionData


def record_damage_event(
    session: SessionData,
    attacker: CombatParticipant,
    action: dict,
    target: CombatParticipant,
    result: AttackResult | SaveDamageResult | AutomaticDamageResult,
) -> str:
    if isinstance(result, AutomaticDamageResult):
        session.record_event(
            f"{attacker.name} uses {action.get('name', '')} on {target.name}: {result.damage} automatic damage"
        )
        return "automatic damage"
    if isinstance(result, SaveDamageResult):
        save_outcome = "succeeded" if result.save_success else "failed"
        session.record_event(
            f"{attacker.name} uses {action.get('name', '')} on {target.name}: "
            f"{result.save_type} save {save_outcome}, {result.damage} damage"
        )
        return f"{result.save_type} save {save_outcome}"
    hit_miss = "hit" if result.hit else "miss"
    session.record_event(f"{attacker.name} attacks {target.name}: {hit_miss}, {result.damage} damage")
    return hit_miss
