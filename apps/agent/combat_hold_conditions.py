"""Offer a reaction to a save-only condition after the effect has resolved."""

import reaction_gate
import reaction_windows
from combat_hold_actions import _held_declaration
from combat_state import CombatState
from encounter_actions import action_kind


def window_for(state: CombatState, head: dict, action: dict, summary: dict) -> dict | None:
    if reaction_windows.POST_ROLL in head["opened"]:
        return None
    triggers = reaction_windows.condition_triggers(action, imposed=summary.get("condition_inflicted") is not None)
    if not triggers:
        return None
    window = reaction_windows.open_window_for(
        round_number=state.round_number,
        seq=head["seq"],
        stage=reaction_windows.POST_ROLL,
        actor_id=head["actor_id"],
        target_id=_held_declaration(head).target_id,
        action_kind=action_kind(action),
        triggers=triggers,
    )
    return window if reaction_gate.offers_for_window(state, window) else None
