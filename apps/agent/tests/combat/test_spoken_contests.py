from unittest.mock import MagicMock

import pytest
from combat._reaction_helpers import reaction_state, silence
from voice_condition_fixtures import participant

import reaction_spend
from conditions import apply_condition


@pytest.mark.parametrize("ability_id", ["marshal_countermand", "spy_plausible_deniability", "diplomat_objection"])
@pytest.mark.parametrize("restriction", ["source_silence", "recipient_silence", "recipient_deafened"])
def test_contested_consumer_checks_delivery_before_rng(ability_id, restriction):
    import combat_reaction_effect

    state = reaction_state(ability_id)
    assert state.open_window is not None
    if restriction == "source_silence":
        silence(state, "player_1")
    elif restriction == "recipient_silence":
        silence(state, "goblin_scout_1")
    else:
        participant(state, "goblin_scout_1").conditions = apply_condition([], "deafened", source="test")
    participant(state, "player_1").attributes = {"charisma": 16}
    participant(state, "goblin_scout_1").attributes = {"charisma": 12, "wisdom": 12}
    state.reactions_available["player_1"] = reaction_spend.spend(ability_id, state.open_window, held_seq=0)
    rng = MagicMock(randint=MagicMock(side_effect=AssertionError("ineligible contest rolled")))
    packets = combat_reaction_effect.close(
        state, state.held_actions[0], state.open_window, attack_action={}, contest_rng=rng
    )
    assert packets[0]["mechanical_effect"] is None
    assert reaction_spend.is_spent(state.reactions_available["player_1"])
    rng.randint.assert_not_called()


def test_stored_contest_replays_without_new_delivery_or_rng():
    import combat_reaction_effect

    state = reaction_state("diplomat_objection")
    assert state.open_window is not None
    participant(state, "player_1").attributes = {"charisma": 16}
    participant(state, "goblin_scout_1").attributes = {"wisdom": 12}
    state.reactions_available["player_1"] = reaction_spend.spend("diplomat_objection", state.open_window, held_seq=0)
    first = combat_reaction_effect.close(
        state,
        state.held_actions[0],
        state.open_window,
        attack_action={},
        contest_rng=MagicMock(randint=MagicMock(return_value=10)),
    )
    assert first[0]["mechanical_effect"] == "action_hesitated"
    silence(state, "player_1")
    participant(state, "goblin_scout_1").conditions = apply_condition([], "deafened", source="test")
    replay = combat_reaction_effect.close(
        state,
        state.held_actions[0],
        state.open_window,
        attack_action={},
        contest_rng=MagicMock(randint=MagicMock(side_effect=AssertionError("rerolled"))),
    )
    assert replay == first
