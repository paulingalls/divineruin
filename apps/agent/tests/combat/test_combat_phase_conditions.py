"""Beat-4 (WRAP) condition-tick integration in the pure phase engine (M4.3, story-002).

advance_combat_phase advances conditions once per phase at the WRAP beat: durations
decrement, expired conditions drop off the returned state, and save-to-clear conditions
(only Frightened, per the story-001 catalog) surface a save signal in
WrapOutcome.tick_conditions_due for orchestration to resolve. The engine stays pure — it
ticks the deep-copied next_state and never rolls or touches the DB.
"""

import copy

from combat_phase import PhaseBeat, advance_combat_phase
from conditions import apply_condition
from session_data import CombatParticipant, CombatState


def _wrap_state(player_conditions=None, enemy_fallen=False, player_fallen=False):
    """A CombatState parked at the WRAP beat. The player carries the given conditions."""
    return CombatState(
        combat_id="combat_test123",
        participants=[
            CombatParticipant(
                id="player_1",
                name="Kael",
                type="player",
                initiative=15,
                hp_current=25,
                hp_max=25,
                ac=14,
                is_fallen=player_fallen,
                conditions=player_conditions or [],
            ),
            CombatParticipant(
                id="goblin_scout_1",
                name="Goblin Scout",
                type="enemy",
                initiative=12,
                hp_current=7,
                hp_max=7,
                ac=13,
                xp_value=50,
                is_fallen=enemy_fallen,
            ),
        ],
        initiative_order=["player_1", "goblin_scout_1"],
        round_number=1,
        current_turn_index=0,
        location_id="accord_guild_hall",
        beat="wrap",
    )


def _player_conditions(state):
    """The player participant's conditions, with a None-narrowing assert for pyright."""
    p = state.get_participant("player_1")
    assert p is not None
    return p.conditions


# --- Slice 1: CombatParticipant carries conditions ---


def test_participant_conditions_defaults_empty():
    p = CombatParticipant(id="p", name="P", type="player", initiative=1, hp_current=1, hp_max=1, ac=10)
    assert p.conditions == []


def test_conditions_round_trip_through_to_dict():
    state = _wrap_state(player_conditions=[{"type": "stunned", "duration": 1, "source": "x", "stacks": 1}])
    restored = CombatState.from_dict(state.to_dict())
    assert _player_conditions(restored) == [{"type": "stunned", "duration": 1, "source": "x", "stacks": 1}]


# --- Slice 2: WrapOutcome.tick_conditions_due exists; existing wrap behavior intact ---


def test_wrap_with_no_conditions_yields_empty_tick_due():
    _, adv = advance_combat_phase(_wrap_state())
    assert adv.wrap is not None
    assert adv.wrap.tick_conditions_due == []


def test_wrap_preserves_existing_outcome_fields():
    next_state, adv = advance_combat_phase(_wrap_state())
    assert adv.wrap is not None
    # Existing wrap behavior is unchanged by the conditions wiring.
    assert adv.wrap.resonance_decay == 1
    assert adv.wrap.combat_ended is False
    assert adv.wrap.death_saves_due == []
    assert next_state.round_number == 2  # looped back to a new declaration phase
    assert next_state.beat == PhaseBeat.DECLARATION


# --- Slice 3: durations decrement and expire on the returned state ---


def test_wrap_decrements_duration():
    conds = apply_condition([], "shielded", duration=2)
    next_state, _ = advance_combat_phase(_wrap_state(player_conditions=conds))
    assert _player_conditions(next_state)[0]["duration"] == 1


def test_wrap_drops_expired_condition():
    conds = apply_condition([], "shielded", duration=1)
    next_state, _ = advance_combat_phase(_wrap_state(player_conditions=conds))
    assert _player_conditions(next_state) == []


def test_wrap_keeps_until_cleared_condition():
    conds = apply_condition([], "poisoned")  # duration None
    next_state, _ = advance_combat_phase(_wrap_state(player_conditions=conds))
    assert _player_conditions(next_state) == conds


# --- Slice 4: save-to-clear conditions surface a tagged save event ---


def test_wrap_surfaces_frightened_save_tagged_with_actor():
    conds = apply_condition([], "frightened", source="wraith")
    conds = apply_condition(conds, "poisoned")  # no tick save
    _, adv = advance_combat_phase(_wrap_state(player_conditions=conds))
    assert adv.wrap is not None
    assert adv.wrap.tick_conditions_due == [
        {"actor_id": "player_1", "type": "frightened", "save": "wis", "source": "wraith"}
    ]


# --- Slice 5: tick runs when combat ends; engine stays pure ---


def test_wrap_ticks_conditions_even_when_combat_ends():
    conds = apply_condition([], "shielded", duration=1)
    # enemy fallen -> victory ends combat this wrap, but conditions still tick.
    next_state, adv = advance_combat_phase(_wrap_state(player_conditions=conds, enemy_fallen=True))
    assert adv.wrap is not None
    assert adv.wrap.combat_ended is True
    assert _player_conditions(next_state) == []


def test_advance_does_not_mutate_input_state():
    conds = apply_condition([], "shielded", duration=2)
    state = _wrap_state(player_conditions=conds)
    snapshot = copy.deepcopy(state.to_dict())
    advance_combat_phase(state)
    assert state.to_dict() == snapshot
