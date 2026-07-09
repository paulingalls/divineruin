"""Tests for cast_modifiers — the pure per-cast composition layer (M24 story-006).

These primitives were extracted from spell_casting._resolve_cast, which had grown past the
500-line cap. Refactor Mode requires a direct behavior test for each new primitive: the
original caller's tests reach them only through _resolve_cast, so a bug in an edge case no
cast test happens to drive would pass unnoticed.

Everything here is pure — no conn, no session. The async ward READ stays in _resolve_cast;
what lives here is what the cast does with the answer.
"""

import pytest

import cast_modifiers
import racial_resonance as racial_mod
import resonance
import veil_ward
from spells import Spell


def _spell(*, source="arcane", focus_cost=10, resonance_value=6, spell_id="test_spell") -> Spell:
    return Spell(
        id=spell_id,
        name="Test Spell",
        source=source,
        spell_tier="standard",
        focus_cost=focus_cost,
        mechanics="Deals force damage to one target.",
        narration_cue="A surge of raw power snaps outward.",
        audio_cue="SFX-001",
        resonance_by_source={source: resonance_value} if resonance_value is not None else {},
        terrain_effects={},
    )


class TestComputeGeneratedResonance:
    def test_catalog_value_is_the_ssot(self):
        # A catalog entry wins over the source*focus formula, even when they disagree.
        spell = _spell(resonance_value=6, focus_cost=10)
        assert cast_modifiers.compute_generated_resonance(spell, None, resonance=resonance, racial_mod=racial_mod) == 6

    def test_falls_back_to_the_formula_without_a_catalog_entry(self):
        spell = _spell(source="arcane", focus_cost=10, resonance_value=None)
        expected = resonance.calculate_resonance_generated(10, "arcane", terrain="normal")
        got = cast_modifiers.compute_generated_resonance(spell, None, resonance=resonance, racial_mod=racial_mod)
        assert got == expected

    def test_korath_primal_cast_reduces_generation(self):
        spell = _spell(source="primal", resonance_value=6)
        got = cast_modifiers.compute_generated_resonance(spell, "korath", resonance=resonance, racial_mod=racial_mod)
        assert got == 5

    def test_korath_reduction_does_not_apply_to_arcane(self):
        spell = _spell(source="arcane", resonance_value=6)
        got = cast_modifiers.compute_generated_resonance(spell, "korath", resonance=resonance, racial_mod=racial_mod)
        assert got == 6

    def test_non_korath_primal_cast_is_untouched(self):
        spell = _spell(source="primal", resonance_value=6)
        got = cast_modifiers.compute_generated_resonance(spell, "human", resonance=resonance, racial_mod=racial_mod)
        assert got == 6

    def test_korath_reduction_floors_at_zero_and_skips_a_cantrip(self):
        # generated 0 must stay 0: the > 0 guard keeps a floored cantrip out of the
        # resonance write / HUD push gates downstream.
        spell = _spell(source="primal", resonance_value=0)
        got = cast_modifiers.compute_generated_resonance(spell, "korath", resonance=resonance, racial_mod=racial_mod)
        assert got == 0

    def test_primal_build_without_a_catalog_entry_fails_loud(self):
        # The one path that still reaches the terrain lookup; no runtime terrain map exists.
        spell = _spell(source="primal", resonance_value=None)
        with pytest.raises(ValueError):
            cast_modifiers.compute_generated_resonance(spell, None, resonance=resonance, racial_mod=racial_mod)

    def test_race_none_never_takes_a_racial_branch(self):
        spell = _spell(source="primal", resonance_value=6)
        assert cast_modifiers.compute_generated_resonance(spell, None, resonance=resonance, racial_mod=racial_mod) == 6


class TestApplyWardHalving:
    def test_active_ward_halves_rounding_down(self):
        assert cast_modifiers.apply_ward_halving(7, True, veil_ward=veil_ward) == 3

    def test_inactive_ward_leaves_generation_untouched(self):
        assert cast_modifiers.apply_ward_halving(7, False, veil_ward=veil_ward) == 7

    def test_zero_generation_is_never_halved(self):
        # Guards the generated > 0 gate: halve_generation(0) is 0 anyway, but the guard is
        # what keeps a cantrip out of the write/publish paths, so it must survive extraction.
        assert cast_modifiers.apply_ward_halving(0, True, veil_ward=veil_ward) == 0
