"""Validate which player reactions may answer the current combat window."""

from __future__ import annotations

import abilities
import reaction_spend
import reaction_windows
from condition_restrictions import cannot_act
from session_data import CombatState

# Ally windows name somebody other than the reactor by definition; enemy event windows describe
# the acting enemy rather than the player affected by the reaction.
SELF_TARGETED_REACTION_WINDOWS = frozenset({"on_hit", "on_targeted", "on_condition_imposed"})
UNBOUND_REACTION_WINDOWS = frozenset(
    {"on_ally_hit", "on_ally_targeted", "on_enemy_miss", "on_enemy_move", "on_spell_cast", "on_enemy_action"}
)
HOLLOW_CATEGORIES = frozenset({"hollow_drift", "hollow_rend"})
_SOCIAL_SUBJECTS = {
    "marshal_countermand": "command",
    "spy_plausible_deniability": "accusation",
}


def is_hollow(actor) -> bool:
    return actor.category in HOLLOW_CATEGORIES or actor.type == "temporary_hollowed"


def _validate_social_subject(state: CombatState, actor_id: str, ability_id: str, window: dict) -> None:
    actual = window["action_kind"]
    required = _SOCIAL_SUBJECTS.get(ability_id)
    if required is not None and actual != required:
        raise ValueError(f"reaction {ability_id!r} requires subject {required!r}, but held subject is {actual!r}")
    if ability_id == "spy_plausible_deniability" and window["target_id"] != actor_id:
        raise ValueError(
            f"reaction {ability_id!r} belongs to accused reactor {actor_id!r}, "
            f"but the accusation targets {window['target_id']!r}"
        )
    if ability_id == "diplomat_objection":
        if window["stage"] != reaction_windows.PRE_ROLL:
            raise ValueError(
                f"reaction {ability_id!r} requires stage {reaction_windows.PRE_ROLL!r}, "
                f"but the open stage is {window['stage']!r}"
            )
        acting_enemy = state.get_participant(window["actor_id"])
        if acting_enemy is None:
            raise ValueError(f"reaction window names missing actor {window['actor_id']!r}")
        if is_hollow(acting_enemy):
            raise ValueError(f"reaction {ability_id!r} has no effect on Hollow actor {acting_enemy.id!r}")


def validate_reaction_activation(state: CombatState, actor_id: str, ability_id: str) -> None:
    """Raise unless ``actor_id`` may spend a reaction on ``ability_id`` right now.

    The permission is an OPEN WINDOW (story-017, decision 46), not a pre-declaration: the player
    shouts "I block!" in conversational time, against a held enemy blow the DM has just narrated.
    Beat 1 could not know whether that blow would hit, miss, or land at all, so the declared
    trigger was an unmakeable judgement; the window the Beat-3 pump is paused on knows.

    The open-window check is deliberately not a beat comparison. A beat gate has to track the
    pause it guards and cannot fail loud when it drifts: the RESOLUTION gate this replaced was
    left behind by story-016's move of the pause to NARRATION, and silently refused every held
    window it existed to protect.

    Validation ONLY -- it deliberately does not return a new state. An earlier shape deep-copied
    ``state`` here and the caller assigned the copy back after its await, which erased anything
    another in-place writer committed meanwhile (draethar_inner_fire mutates participants
    directly; it holds combat_state_lock now, but a snapshot still cannot see a write taken after
    it). The caller records the spend as one field write instead."""
    _validate_for_window(state, actor_id, ability_id, state.open_window)


def _validate_for_window(state: CombatState, actor_id: str, ability_id: str, window: dict | None) -> None:
    actor = state.get_participant(actor_id)
    if actor is None or actor.type != "player":
        raise ValueError("only players can activate reactions")
    if actor.is_fallen:
        raise ValueError(f"player {actor_id!r} is down and cannot react")
    if blocked := cannot_act(actor.conditions):
        raise ValueError(f"{actor.name} ({actor.id}) is {blocked[0]} and cannot react")

    if actor.has_reaction_ability is not True:
        raise ValueError(f"player {actor_id!r} owns no reaction ability, so {ability_id!r} cannot be spent")
    # Narrower than has_reaction_ability on purpose: reaction_ids is what offered_reactions
    # surfaces, so the gate refuses exactly the ids the DM was never handed.
    if ability_id not in actor.reaction_ids:
        raise ValueError(f"player {actor_id!r} does not own reaction {ability_id!r}")

    if window is None:
        raise ValueError("no reaction window is open; a reaction interrupts a held enemy action")

    catalog_window = abilities.get_ability(ability_id).window
    if catalog_window not in window["triggers"]:
        raise ValueError(
            f"reaction {ability_id!r} fires on {catalog_window!r}, but the open window "
            f"{window['id']!r} offers {window['triggers']}"
        )

    _validate_social_subject(state, actor_id, ability_id, window)

    if catalog_window in SELF_TARGETED_REACTION_WINDOWS:
        if window["target_id"] != actor_id:
            raise ValueError(
                f"reaction {ability_id!r} requires a window targeting reactor {actor_id!r}, "
                f"but the open window targets {window['target_id']!r}"
            )
    elif catalog_window not in UNBOUND_REACTION_WINDOWS:
        raise ValueError(f"unclassified reaction window {catalog_window!r} has no target-binding policy")

    if reaction_spend.is_spent(state.reactions_available.get(actor_id)):
        raise ValueError(f"player {actor_id!r} already spent their reaction this round")


def offered_reactions(state: CombatState) -> list[dict]:
    """The reaction ids the DM may pass to activate at the open window (constraint 6).

    Candidate and open windows use the same activation validator."""
    return offers_for_window(state, state.open_window)


def offers_for_window(state: CombatState, window: dict | None) -> list[dict]:
    """Offer reactions for a candidate window without opening it."""
    offered = []
    for participant in state.participants:
        for ability_id in participant.reaction_ids:
            # Outside the try: a stored id the catalog no longer knows is a defect, not an ineligible reaction.
            ability = abilities.get_ability(ability_id)
            try:
                _validate_for_window(state, participant.id, ability_id, window)
            except ValueError:
                continue
            offered.append({"actor_id": participant.id, "id": ability_id, "name": ability.name})
    return offered
