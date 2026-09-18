import pytest
from combat._helpers import _make_combat_state

import conditions
from combat_phase import PhaseBeat, advance_combat_phase
from session_data import CombatParticipant


def _target_band_state():
    state = _make_combat_state()
    state.participants.extend(
        [
            CombatParticipant(
                id="companion_1",
                name="Mira",
                type="companion",
                initiative=14,
                hp_current=18,
                hp_max=18,
                ac=13,
                action_pool=[{"name": "Shortsword", "damage": "1d6", "damage_type": "piercing"}],
            ),
            CombatParticipant(
                id="enemy_commander",
                name="Ashmark Captain",
                type="enemy",
                initiative=11,
                hp_current=24,
                hp_max=24,
                ac=15,
                action_pool=[{"name": "Rally", "kind": "command"}],
            ),
        ]
    )
    return state


@pytest.mark.parametrize(
    ("actor_id", "declaration", "expected_names"),
    [
        (
            "player_1",
            {"type": "attack", "action": "Longsword", "target_id": "companion_1"},
            ("Kael", "player_1", "Mira", "companion_1"),
        ),
        (
            "companion_1",
            {"type": "maneuver", "target_id": "player_1"},
            ("Mira", "companion_1", "Kael", "player_1"),
        ),
        (
            "enemy_commander",
            {"type": "attack", "action": "Rally", "target_id": "goblin_scout_1"},
            ("Ashmark Captain", "enemy_commander", "Goblin Scout", "goblin_scout_1"),
        ),
    ],
    ids=["player-attacks-companion", "companion-shoves-player", "enemy-commands-enemy"],
)
def test_same_band_target_is_refused_and_names_actor_and_target(actor_id, declaration, expected_names):
    state = _target_band_state()

    with pytest.raises(ValueError) as excinfo:
        advance_combat_phase(state, {actor_id: declaration})

    message = str(excinfo.value)
    for name in expected_names:
        assert name in message


def test_self_targeted_attack_is_refused():
    """An ATTACK naming its own actor is a same-band target too: it would resolve as a real
    swing against the actor's own AC. Only the stand MANEUVER may name its own actor."""
    state = _target_band_state()

    with pytest.raises(ValueError) as excinfo:
        advance_combat_phase(state, {"player_1": {"type": "attack", "action": "Longsword", "target_id": "player_1"}})

    assert "Kael (player_1) cannot target Kael (player_1)" in str(excinfo.value)


def test_player_ability_can_target_an_ally():
    state = _target_band_state()
    declaration = {"type": "ability", "action": "divine_bless", "target_id": "companion_1"}

    next_state, _ = advance_combat_phase(state, {"player_1": declaration})

    assert next_state.beat == PhaseBeat.RESOLUTION
    assert next_state.pending_declarations == {"player_1": declaration}


def test_prone_actor_can_target_self_to_stand():
    state = _target_band_state()
    player = state.get_participant("player_1")
    assert player is not None
    player.conditions = conditions.apply_condition(player.conditions, "prone", source="test")
    declaration = {"type": "maneuver", "target_id": "player_1"}

    next_state, _ = advance_combat_phase(state, {"player_1": declaration})

    assert next_state.beat == PhaseBeat.RESOLUTION
    assert next_state.pending_declarations == {"player_1": declaration}


def test_enemy_command_can_target_the_opposing_band():
    state = _target_band_state()
    declaration = {"type": "attack", "action": "Rally", "target_id": "player_1"}

    next_state, _ = advance_combat_phase(state, {"enemy_commander": declaration})

    assert next_state.beat == PhaseBeat.RESOLUTION
    assert next_state.pending_declarations == {"enemy_commander": declaration}


@pytest.mark.parametrize(
    "declaration",
    [
        {"type": "attack", "action": "Longsword", "target_id": "missing_target"},
        {"type": "maneuver", "target_id": "missing_target"},
    ],
    ids=["attack", "maneuver"],
)
def test_unknown_target_is_refused_at_declaration(declaration):
    state = _target_band_state()

    with pytest.raises(ValueError) as excinfo:
        advance_combat_phase(state, {"player_1": declaration})

    message = str(excinfo.value)
    assert "Kael" in message
    assert "player_1" in message
    assert "missing_target" in message
