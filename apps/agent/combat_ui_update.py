"""Pure COMBAT_UI_UPDATE packet projection.

Combat start publishes it directly. Reaction-window pauses and non-terminal Beat-4 wraps buffer
it in the phase EventSink, so rolled-back state never reaches the client.
"""

from session_data import CombatParticipant, CombatState


def _project_condition(cond: dict) -> dict:
    """Project a participant condition to the minimal wire shape mobile reads.

    Mobile's parseCondition reads {type, stacks, source} only; `duration` and
    `stage` stay server-side. `stacks` defaults to 1 (matches mobile's
    fail-soft) so a Hollowed-shaped condition (no stacks field) is safe.
    """
    return {
        "type": cond["type"],
        "stacks": cond.get("stacks", 1),
        "source": cond.get("source", ""),
    }


def _active_id(state: CombatState) -> str | None:
    """The id of the next-up LIVE actor, scanning forward from current_turn_index.

    initiative_order is never pruned on death — combat_phase keeps fallen / dead
    participants in the order — so we must skip them here, otherwise the HUD
    highlights a corpse as the next-up combatant. Returns None when the order is
    empty, the index is degenerate, or every remaining actor at-or-after the
    index is is_fallen / is_dead (combat is effectively over)."""
    order = state.initiative_order
    idx = state.current_turn_index
    if not order or idx < 0 or idx >= len(order):
        return None
    by_id = {p.id: p for p in state.participants}
    for actor_id in order[idx:]:
        actor = by_id.get(actor_id)
        if actor is not None and not actor.is_fallen and not actor.is_dead:
            return actor_id
    return None


def _project_combatant(p: CombatParticipant, active_id: str | None) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "isAlly": p.is_ally,
        "hpCurrent": p.hp_current,
        "hpMax": p.hp_max,
        "conditions": [_project_condition(c) for c in p.conditions],
        "isActive": p.id == active_id,
    }


def build_combat_ui_update(state: CombatState) -> dict:
    """Build the current tracker packet without publishing it."""
    active_id = _active_id(state)
    return {
        "round": state.round_number,
        "combatants": [_project_combatant(p, active_id) for p in state.participants],
    }
