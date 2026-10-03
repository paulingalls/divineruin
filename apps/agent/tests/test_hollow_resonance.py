"""Geometry, composition and catalog snapshot invariants."""

import pytest
from _hollow_resonance_fixtures import scenario
from voice_condition_fixtures import participant

import combat_spatial
from combat_state import CombatState
from hollow_resonance import apply_corruption_aura, location_bonus, resolve_resonance_on_death

ORIGIN = {"x": 0, "y": 0, "z": 0}


@pytest.mark.parametrize("radius,distance,bonus", [(0, 0, 1), (0, 0.01, 0), (5, 5, 1), (5, 5.01, 0)])
def test_boundary_and_contact(radius, distance, bonus):
    center = {**ORIGIN, "x": distance}
    assert apply_corruption_aura(2, 2, 0, ORIGIN, [(center, radius)]) == 2 + bonus


@pytest.mark.parametrize("level,bonus", [(0, 1), (1, 1), (2, 2), (3, 2)])
def test_overlapping_and_location_bonus_use_max(level, bonus):
    assert apply_corruption_aura(2, 2, level, ORIGIN, [(ORIGIN, 5), (ORIGIN, 30)]) == 2 + bonus
    assert apply_corruption_aura(0, 0, level, ORIGIN, [(ORIGIN, 5)]) == 0


@pytest.mark.parametrize("value", [-1, True, 4, None])
def test_unsupported_location_rejected(value):
    with pytest.raises(ValueError):
        location_bonus(value)


@pytest.mark.parametrize("field,label", [(0, "generation"), (1, "Focus cost"), (2, "corruption aura")])
@pytest.mark.parametrize("value", [-1, True, 1.5, None])
def test_invalid_aura_inputs_are_refused(field, label, value):
    inputs = [2, 2, 5]
    inputs[field] = value
    with pytest.raises(ValueError, match=label):
        apply_corruption_aura(inputs[0], inputs[1], 0, ORIGIN, [(ORIGIN, inputs[2])])


def test_death_halves_each_delta_before_addition():
    assert resolve_resonance_on_death(3, True) + resolve_resonance_on_death(3, True) == 2
    assert resolve_resonance_on_death(0, False) == 0
    assert resolve_resonance_on_death(1, True) == 0
    for value in (-1, True, 1.5):
        with pytest.raises(ValueError):
            resolve_resonance_on_death(value, False)


def test_snapshot_and_receipt_roundtrip():
    _, state, enemy = scenario()
    assert enemy.hollow == {"corruption_aura": 5, "resonance_on_death": 1}
    enemy.hollow_death_resolved = True
    loaded = CombatState.from_dict(state.to_dict())
    assert participant(loaded, enemy.id).hollow == enemy.hollow
    assert participant(loaded, enemy.id).hollow_death_resolved
    assert enemy.hollow is not None
    enemy.hollow["corruption_aura"] = 100
    assert participant(loaded, enemy.id).hollow == {"corruption_aura": 5, "resonance_on_death": 1}


@pytest.mark.parametrize("defect", ["boundary", "contact", "stacking"])
def test_geometry_and_stacking_faults(monkeypatch, defect):
    if defect == "boundary":
        monkeypatch.setattr(combat_spatial, "inside", lambda a, b, r: combat_spatial.distance(a, b) < r)
        with pytest.raises(AssertionError):
            test_boundary_and_contact(5, 5, 1)
    elif defect == "contact":
        monkeypatch.setattr(combat_spatial, "inside", lambda a, b, r: r == 0 or combat_spatial.distance(a, b) <= r)
        with pytest.raises(AssertionError):
            test_boundary_and_contact(0, 0.01, 0)
    else:
        import hollow_resonance

        original = hollow_resonance.apply_corruption_aura
        monkeypatch.setitem(globals(), "apply_corruption_aura", lambda *args: original(*args) + 1)
        with pytest.raises(AssertionError):
            test_overlapping_and_location_bonus_use_max(2, 2)
