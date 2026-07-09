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
import hollow_echo
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


class TestComputeEffectiveResonance:
    def _effective(self, generated, current, race, in_combat):
        return cast_modifiers.compute_effective_resonance(
            generated, current, race, in_combat, resonance=resonance, racial_mod=racial_mod
        )

    def test_sheds_one_decay_round_then_accrues(self):
        # OOC: base 5 decays by 1 -> 4, then this cast's 3 lands -> 7.
        assert self._effective(3, 5, None, False) == 7

    def test_human_sheds_an_extra_round(self):
        # Adaptive Resonance: base 1/round +1 => 2/round. 5 - 2 + 3 = 6.
        assert self._effective(3, 5, "human", False) == 6

    def test_in_combat_suppresses_the_cast_paced_shed(self):
        # The WRAP beat is the canonical decay clock in combat; an in-combat cast only generates.
        assert self._effective(3, 5, None, True) == 8

    def test_in_combat_suppresses_the_shed_for_a_human_too(self):
        assert self._effective(3, 5, "human", True) == 8

    def test_a_cantrip_skips_decay_entirely(self):
        # generated 0 -> no decay, no accrual: the standing value is left exactly as it was.
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


class TestWardCombatModifiers:
    def _mods(self, state, ward_active):
        return cast_modifiers.ward_combat_modifiers(state, ward_active, resonance=resonance, veil_ward=veil_ward)

    def test_unwarded_returns_the_states_own_modifiers(self):
        assert self._mods("stable", False) == {"damage_dice": 0, "dc": 0}

    def test_active_ward_folds_in_the_die_and_dc_penalty(self):
        assert self._mods("stable", True) == {"damage_dice": -1, "dc": -1}

    def test_ward_penalty_stacks_onto_a_nonzero_state(self):
        base = resonance.get_state_modifiers("overreach")
        got = self._mods("overreach", True)
        assert got["damage_dice"] == base["damage_dice"] - 1
        assert got["dc"] == base["dc"] - 1

    def test_never_mutates_the_shared_state_modifier_table(self):
        # get_state_modifiers hands back a fresh dict; two warded calls must not compound.
        first = self._mods("stable", True)
        second = self._mods("stable", True)
        assert first == second == {"damage_dice": -1, "dc": -1}
        assert resonance.get_state_modifiers("stable") == {"damage_dice": 0, "dc": 0}


class _FixedDice:
    """dice_mod stub returning a scripted sequence of d20 totals, in call order."""

    def __init__(self, *totals):
        self._totals = list(totals)
        self.rolls = []

    def roll(self, expr):
        total = self._totals.pop(0)
        self.rolls.append(expr)
        return type("Roll", (), {"total": total})()


class TestResolveOverreachEcho:
    def _resolve(self, dice, *, race=None, ward_active=False, effective_resonance=9):
        return cast_modifiers.resolve_overreach_echo(
            effective_resonance,
            race,
            ward_active,
            dice_mod=dice,
            hollow_echo=hollow_echo,
            veil_ward=veil_ward,
            racial_mod=racial_mod,
        )

    def test_unwarded_echo_bands_on_the_bare_roll(self):
        echo, warned = self._resolve(_FixedDice(12))
        assert echo.band == "veil_scar"
        assert warned is False

    def test_active_ward_adds_four_and_softens_the_band(self):
        # Same roll, same resonance: only the +4 moves 12 -> 16, veil_scar -> whisper.
        echo, warned = self._resolve(_FixedDice(12), ward_active=True)
        assert echo.band == "whisper"
        assert warned is False

    def test_vaelti_rolls_a_second_d20_and_takes_the_better(self):
        dice = _FixedDice(3, 15)
        echo, warned = self._resolve(dice, race="vaelti")
        assert echo.effective_roll == 15  # advantage took the higher of 3 and 15
        assert warned is True
        assert dice.rolls == ["d20", "d20"]  # base roll FIRST, then the advantage roll

    def test_non_vaelti_rolls_exactly_once_and_never_warns(self):
        dice = _FixedDice(12)
        _echo, warned = self._resolve(dice, race="korath")
        assert warned is False
        assert dice.rolls == ["d20"]

    def test_race_none_rolls_exactly_once(self):
        dice = _FixedDice(12)
        _echo, warned = self._resolve(dice, race=None)
        assert warned is False
        assert dice.rolls == ["d20"]

    def test_below_overreach_fails_loud(self):
        with pytest.raises(ValueError):
            self._resolve(_FixedDice(12), effective_resonance=8)
