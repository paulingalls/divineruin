"""Deterministic concentration save DCs and default caster state."""

import pytest

import concentration
from session_data import ConcentrationState, SessionData


@pytest.mark.parametrize(
    "damage,expected_dc",
    [
        (0, 10),  # no damage -> floor of 10
        (1, 10),
        (18, 10),  # 18//2 = 9 -> floored to 10
        (19, 10),  # 19//2 = 9 -> floored to 10
        (20, 10),  # 20//2 = 10 -> exactly the floor
        (21, 10),  # 21//2 = 10
        (22, 11),  # 22//2 = 11 -> above the floor
        (50, 25),
    ],
)
def test_check_concentration_dc_is_max_10_half_damage(damage, expected_dc):
    assert concentration.check_concentration(damage) == expected_dc


def test_check_concentration_rejects_negative_damage():
    with pytest.raises(ValueError, match="damage"):
        concentration.check_concentration(-1)


def test_session_concentration_defaults_to_inactive():
    sd = SessionData(player_id="p1", location_id="loc1")
    assert isinstance(sd.concentration, ConcentrationState)
    assert sd.concentration.spell_id is None
    assert sd.concentration.is_active is False


def test_concentration_state_is_active_when_spell_set():
    assert ConcentrationState(spell_id="arcane_fly").is_active is True
