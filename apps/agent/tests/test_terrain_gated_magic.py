"""In-code primal formula builds absent from the seeded command catalog."""

from dataclasses import replace

import pytest
from _spell_casting_helpers import _spell

import cast_modifiers
import racial_resonance
import resonance
import veil_ward


@pytest.mark.parametrize("focus,race,ward,expected", [(3, None, False, 1), (25, "korath", True, 2)])
def test_unmapped_primal_composes_terrain_reduction_before_ward(focus, race, ward, expected):
    spell = replace(_spell(source="primal", focus_cost=focus), resonance_by_source={})
    generated = cast_modifiers.compute_generated_resonance(
        spell, race, terrain="forest", resonance=resonance, racial_mod=racial_resonance
    )
    assert cast_modifiers.apply_ward_halving(generated, ward, veil_ward=veil_ward) == expected
