"""Hearing-only checks and current spoken bonus-die eligibility."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from session_data import CombatState

from conditions import get_condition_effects
from spell_voice_rules import is_silenced


def validate_hearing_check(skill: str, hearing_only: bool) -> None:
    if not isinstance(hearing_only, bool):
        raise ValueError("hearing_only must be a boolean")
    if hearing_only and skill.lower() != "perception":
        raise ValueError("hearing_only=true requires Perception")


def auto_fail_hearing_perception(active_conditions, *, skill, hearing_only):
    validate_hearing_check(skill, hearing_only)
    return hearing_only and "auto_fail_hearing_perception" in get_condition_effects(active_conditions).restrictions


def no_spoken_buffs(active_conditions, *, state: CombatState | None = None, actor_id: str | None = None):
    if "no_spoken_buffs" in get_condition_effects(active_conditions).restrictions:
        return True
    if state is None:
        return False
    if not isinstance(actor_id, str):
        raise ValueError("spoken buff requires a positioned actor ID")
    return is_silenced(state, actor_id)


def roll_data(player: dict, state: CombatState | None, actor_id: str):
    participant = state.get_participant(actor_id) if state is not None else None
    active = participant.conditions if participant is not None else player.get("conditions") or []
    return {
        **player,
        "conditions": active,
        "spoken_buffs_eligible": not no_spoken_buffs(active, state=state, actor_id=actor_id),
    }


def spoken_buff_targets(
    condition: str, state: CombatState | None, speaker_id: str, target_ids: list[str], *, rows=None
):
    if condition != "inspired":
        return target_ids
    from spell_voice_rules import require_speech

    require_speech(state, speaker_id)
    eligible = []
    for target_id in target_ids:
        if state is not None:
            target = state.get_participant(target_id)
            if target is None:
                eligible.append(target_id)
                continue
            active = target.conditions
        else:
            active = (rows or {}).get(target_id, {}).get("conditions") or []
        if not no_spoken_buffs(active, state=state, actor_id=target_id):
            eligible.append(target_id)
    if not eligible:
        raise ValueError("Inspired has no eligible recipients who can hear the spoken buff")
    return eligible
