"""Explicit spatial fixtures for condition-aware action tests."""

from types import SimpleNamespace

from declarations import DeclarationType
from session_data import CombatParticipant, CombatState
from tools._helpers import SAMPLE_PLAYER


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


def participant(state: CombatState | None, actor_id: str) -> CombatParticipant:
    assert state is not None
    actor = state.get_participant(actor_id)
    assert actor is not None, actor_id
    return actor


def spatial_record(state: CombatState | None) -> dict:
    assert state is not None and state.spatial is not None
    return state.spatial


# charisma 16 -> +3; persuasion untrained -> the round's argument_total is FixedRng(d20) + 3.
_DIPLOMAT = {**SAMPLE_PLAYER, "attributes": {**SAMPLE_PLAYER["attributes"], "charisma": 16}, "focus": {"current": 20}}


def _make_group_state(*, tags_a=("pragmatic",), tags_b=("suspicious",), enemy_a_fallen=False):
    """A CombatState with ONE Diplomat and TWO living enemies carrying (by default) DIFFERENT
    resistance profiles, so a single argument round shifts each enemy's disposition independently."""
    return place_actors(
        CombatState(
            combat_id="combat_group_test",
            participants=[
                CombatParticipant(
                    id="player_1", name="Kael", type="player", initiative=15, hp_current=25, hp_max=25, ac=14
                ),
                CombatParticipant(
                    id="enemy_a",
                    name="Mawling A",
                    type="enemy",
                    initiative=12,
                    hp_current=18,
                    hp_max=18,
                    ac=13,
                    attributes={"wisdom": 10},
                    resistance_tags=list(tags_a),
                    is_fallen=enemy_a_fallen,
                ),
                CombatParticipant(
                    id="enemy_b",
                    name="Mawling B",
                    type="enemy",
                    initiative=10,
                    hp_current=18,
                    hp_max=18,
                    ac=13,
                    attributes={"wisdom": 10},
                    resistance_tags=list(tags_b),
                ),
            ],
            initiative_order=["player_1", "enemy_a", "enemy_b"],
            location_id="ruins",
        )
    )


def _decl(argument_type="reason"):
    return SimpleNamespace(type=DeclarationType.ABILITY, action="de_escalate", argument_type=argument_type)
