"""Wild Shape end facts from the encounter row being retired."""

from combat_state import CombatState


def ended_forms(state: CombatState) -> list[dict[str, str]]:
    return [
        {"actor_id": participant.id, "form_id": form["form_id"], "reason": "combat_ended"}
        for participant in state.participants
        if (form := participant.wild_shape) is not None
    ]
