import cast_modifiers
import racial_resonance as racial_mod
import resonance
import veil_ward


class TestComputeEffectiveResonance:
    def _effective(self, generated, current, race, in_combat):
        return cast_modifiers.compute_effective_resonance(
            generated, current, race, in_combat, resonance=resonance, racial_mod=racial_mod
        )

    def test_sheds_one_decay_round_then_accrues(self):
        assert self._effective(3, 5, None, False) == 7

    def test_human_sheds_an_extra_round(self):
        assert self._effective(3, 5, "human", False) == 6

    def test_in_combat_suppresses_the_cast_paced_shed(self):
        # The WRAP beat is the canonical decay clock in combat; an in-combat cast only generates.
        assert self._effective(3, 5, None, True) == 8

    def test_in_combat_suppresses_the_shed_for_a_human_too(self):
        assert self._effective(3, 5, "human", True) == 8

    def test_a_cantrip_skips_decay_entirely(self):
        assert self._effective(0, 5, None, False) == 5

    def test_decay_floors_at_zero(self):
        assert self._effective(2, 0, None, False) == 2


class TestApplyWardHalving:
    def test_active_ward_halves_rounding_down(self):
        assert cast_modifiers.apply_ward_halving(7, True, veil_ward=veil_ward) == 3

    def test_inactive_ward_leaves_generation_untouched(self):
        assert cast_modifiers.apply_ward_halving(7, False, veil_ward=veil_ward) == 7

    def test_zero_generation_is_never_halved(self):
        # Guards the generated > 0 gate: halve_generation(0) is 0 anyway, but the guard is
        # what keeps a cantrip out of the write/publish paths, so it must survive extraction.
        assert cast_modifiers.apply_ward_halving(0, True, veil_ward=veil_ward) == 0
