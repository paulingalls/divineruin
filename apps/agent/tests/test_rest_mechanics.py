"""Tests for rest recovery mechanics — short and long rest resource restoration."""

import pytest

from rest_mechanics import apply_long_rest, apply_rest, apply_short_rest


class TestApplyShortRest:
    def test_stamina_full_recovery(self) -> None:
        stamina, _focus = apply_short_rest(current_stamina=3, max_stamina=10, current_focus=10, max_focus=10)
        assert stamina == 10

    def test_focus_half_recovery(self) -> None:
        _stamina, focus = apply_short_rest(current_stamina=10, max_stamina=10, current_focus=0, max_focus=10)
        assert focus == 5

    def test_focus_odd_max_floors(self) -> None:
        _stamina, focus = apply_short_rest(current_stamina=10, max_stamina=10, current_focus=0, max_focus=11)
        assert focus == 5

    def test_focus_already_above_half_not_reduced(self) -> None:
        _stamina, focus = apply_short_rest(current_stamina=10, max_stamina=10, current_focus=8, max_focus=10)
        assert focus == 8

    def test_pools_already_full(self) -> None:
        stamina, focus = apply_short_rest(current_stamina=10, max_stamina=10, current_focus=10, max_focus=10)
        assert stamina == 10
        assert focus == 10

    def test_pools_at_zero(self) -> None:
        stamina, focus = apply_short_rest(current_stamina=0, max_stamina=20, current_focus=0, max_focus=20)
        assert stamina == 20
        assert focus == 10


class TestApplyLongRest:
    def test_all_pools_restored(self) -> None:
        stamina, focus, hp = apply_long_rest(
            current_stamina=3,
            max_stamina=10,
            current_focus=2,
            max_focus=10,
            current_hp=5,
            max_hp=30,
        )
        assert stamina == 10
        assert focus == 10
        assert hp == 30

    def test_hp_restored(self) -> None:
        _stamina, _focus, hp = apply_long_rest(
            current_stamina=10,
            max_stamina=10,
            current_focus=10,
            max_focus=10,
            current_hp=5,
            max_hp=30,
        )
        assert hp == 30


class TestApplyRest:
    def test_short_rest_dispatcher(self) -> None:
        stamina, focus, hp = apply_rest(
            rest_type="short",
            current_stamina=3,
            max_stamina=10,
            current_focus=0,
            max_focus=10,
            current_hp=15,
            max_hp=30,
        )
        assert stamina == 10
        assert focus == 5
        assert hp == 15  # unchanged

    def test_long_rest_dispatcher(self) -> None:
        stamina, focus, hp = apply_rest(
            rest_type="long",
            current_stamina=3,
            max_stamina=10,
            current_focus=2,
            max_focus=10,
            current_hp=5,
            max_hp=30,
        )
        assert stamina == 10
        assert focus == 10
        assert hp == 30

    def test_invalid_rest_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown rest type"):
            apply_rest(
                rest_type="nap",  # type: ignore[arg-type]
                current_stamina=5,
                max_stamina=10,
                current_focus=5,
                max_focus=10,
                current_hp=5,
                max_hp=10,
            )

    def test_e2e_drain_short_then_long(self) -> None:
        # All pools drained
        stamina, focus, hp = apply_rest(
            rest_type="short",
            current_stamina=0,
            max_stamina=20,
            current_focus=0,
            max_focus=16,
            current_hp=5,
            max_hp=30,
        )
        assert stamina == 20
        assert focus == 8
        assert hp == 5

        # Now long rest from the short-rest state
        stamina, focus, hp = apply_rest(
            rest_type="long",
            current_stamina=stamina,
            max_stamina=20,
            current_focus=focus,
            max_focus=16,
            current_hp=hp,
            max_hp=30,
        )
        assert stamina == 20
        assert focus == 16
        assert hp == 30
