"""Combat state changes prepared by actively spent patron gifts."""

from copy import deepcopy

from livekit.agents.llm import ToolError

from combat_state import CombatState
from conditions import apply_condition

BATTLE_CRY = "kaelen_battle_cry_of_the_ironhand"


def battle_cry(state: CombatState | None, actor: str, *, target_id: str | None) -> tuple[CombatState, dict]:
    if state is None:
        raise ToolError("Battle Cry can only be used in combat.")
    participant = state.get_participant(actor)
    if participant is None or participant.type != "player":
        raise ToolError("Battle Cry requires the acting player to be a player participant.")

    updated = deepcopy(state)
    allies = []
    for ally in updated.participants:
        if ally.is_ally:
            ally.conditions = apply_condition(ally.conditions, "battle_cry", duration=2, source=actor)
            allies.append({"id": ally.id, "name": ally.name})
    return updated, {"allies": allies}


ACTIVE_GIFTS = {BATTLE_CRY: battle_cry}
