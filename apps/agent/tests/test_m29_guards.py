"""Fault injection for the M29 acceptance guards (story-022): each reds against its own target.

The guards live in ``tests/acceptance/_m29_guards.py`` but are pure, so their falsifiers run HERE —
in the fast lane, on every push, rather than behind an API key in the tier they were written for.
A green that comes from an assertion which cannot fail is worse than no assertion (constraint 1).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from acceptance._m29_guards import DECLARATIONS, TRUNCATION_WARNING, assert_halved, assert_within_ceiling
from pydantic import ValidationError

_GOOD_DECL = {"kind": "attack", "actor_id": "m29_rogue", "action": "Longsword", "target_id": "mawling_1", "rider": ""}


def test_the_declaration_union_rejects_a_malformed_variant():
    """AC1 leans on this validator, so it reds against the two defects the AC names by hand."""
    DECLARATIONS.validate_python([_GOOD_DECL])
    for missing in ("kind", "target_id"):
        with pytest.raises(ValidationError):
            DECLARATIONS.validate_python([{k: v for k, v in _GOOD_DECL.items() if k != missing}])


def test_the_halving_guard_reds_when_the_full_blow_lands():
    """AC2's guard reds on the exact outcome it exists to catch — the unhalved blow — and on the
    vacuous case where the damage is too small for a halving to be observable at all."""
    with pytest.raises(AssertionError, match="the full blow landed"):
        assert_halved(hp_before=100, full=6, participant_hp=94, db_hp=94)
    with pytest.raises(AssertionError, match="halving is unobservable"):
        assert_halved(hp_before=100, full=1, participant_hp=100, db_hp=100)
    with pytest.raises(AssertionError, match=r"players\.data->hp->current"):
        assert_halved(hp_before=100, full=6, participant_hp=97, db_hp=28)
    assert_halved(hp_before=100, full=6, participant_hp=97, db_hp=97)


def test_the_ceiling_guard_reds_on_each_arm_separately():
    """AC3's guard has two arms, and the step count alone cannot falsify the message match.

    livekit increments ``num_steps`` AFTER emitting the truncation warning, so a real truncation
    always breaks the step arm first. Held at the PERMITTED count with the warning present, the
    message arm is the only thing that can red — which is what says it is wired to the real
    logger and the real string.
    """
    at_permitted = [SimpleNamespace(num_steps=6)]
    assert_within_ceiling(at_permitted, [], max_tool_steps=5)
    with pytest.raises(AssertionError, match="tool_choice='none'"):
        assert_within_ceiling(at_permitted, [f"prefix {TRUNCATION_WARNING} suffix"], max_tool_steps=5)
    with pytest.raises(AssertionError, match="chained 7 steps"):
        assert_within_ceiling([SimpleNamespace(num_steps=7)], [], max_tool_steps=5)
    with pytest.raises(AssertionError, match="no speech handle"):
        assert_within_ceiling([], [], max_tool_steps=5)
