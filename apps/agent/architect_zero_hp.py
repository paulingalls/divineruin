"""Collapse destroyed walls and the walls of a destroyed Architect."""

import architect_encounter
from combat_structures import collapse_wall
from session_data import CombatParticipant, CombatState


def collapse_structure(state: CombatState | None, target: CombatParticipant) -> bool:
    if not target.is_structure:
        return False
    collapse_wall(state, target)
    return True


def collapse_owned_walls(state: CombatState | None, target_id: str) -> None:
    if state is not None and architect_encounter.is_owner(state, target_id):
        architect_encounter.destroyed(state)
