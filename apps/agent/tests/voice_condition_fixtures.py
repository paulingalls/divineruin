"""Explicit spatial fixtures for condition-aware action tests."""

from session_data import CombatParticipant


def place_actors(state, *actor_ids):
    for actor_id in actor_ids:
        if state.get_participant(actor_id) is None:
            state.participants.append(
                CombatParticipant(
                    id=actor_id,
                    name=actor_id,
                    type="player",
                    initiative=15,
                    hp_current=25,
                    hp_max=25,
                    ac=14,
                )
            )
    state.spatial = {
        "positions": {p.id: {"x": 0, "y": 0, "z": 0} for p in state.participants},
        "speeds": {p.id: 30 for p in state.participants},
        "locations": {},
        "zones": {},
    }
    return state
