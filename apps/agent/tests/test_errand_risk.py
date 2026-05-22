"""Errand-risk roll + tables, conformance-pinned to the spec.

game_mechanics_core.md §Companion Risk (L887-892) is the oracle. The TS server
(apps/server/src/errand_risk.ts) keeps a sibling BLOCKED_DANGER_COMBOS pin; both
languages conform to the same spec doc. Risk is rolled here (Python worker, at
resolution) — TS no longer rolls it (ADR 0006).
"""

import random

import pytest

from errand_risk import (
    BLOCKED_DANGER_COMBOS,
    ERRAND_RISK_TABLE,
    is_blocked_combo,
    numeric_to_danger,
    roll_errand_risk,
)


class _FixedRng(random.Random):
    """Stub rng whose randint always returns a fixed roll — deterministic boundaries."""

    def __init__(self, value: int) -> None:
        super().__init__()
        self._value = value

    def randint(self, _a: int, _b: int) -> int:
        return self._value


# game_mechanics_core.md §Companion Risk L887-892 — the 12 populated cells.
SPEC_CELLS = {
    "safe|scout": (0, 0),
    "safe|social": (0, 0),
    "safe|acquire": (0, 0),
    "safe|relationship": (0, 0),
    "moderate|scout": (10, 0),
    "moderate|social": (0, 0),
    "moderate|acquire": (10, 0),
    "moderate|relationship": (0, 0),
    "dangerous|scout": (25, 5),
    "dangerous|social": (0, 0),
    "dangerous|acquire": (20, 0),
    "extreme|scout": (40, 15),
}

SPEC_BLOCKED = {
    "dangerous|relationship",
    "extreme|relationship",
    "extreme|social",
    "extreme|acquire",
}


class TestRiskTableConformance:
    def test_table_matches_spec_cells(self):
        actual = {k: (v["injury_pct"], v["emergency_pct"]) for k, v in ERRAND_RISK_TABLE.items()}
        assert actual == SPEC_CELLS

    def test_no_cells_beyond_spec(self):
        assert set(ERRAND_RISK_TABLE.keys()) == set(SPEC_CELLS.keys())


class TestBlockedCombosConformance:
    def test_blocked_combos_match_spec_na_cells(self):
        assert BLOCKED_DANGER_COMBOS == SPEC_BLOCKED

    @pytest.mark.parametrize("combo", sorted(SPEC_BLOCKED))
    def test_blocked_combo_rejected(self, combo):
        danger, errand = combo.split("|")
        assert is_blocked_combo(danger, errand) is True

    def test_allowed_combo_not_blocked(self):
        assert is_blocked_combo("dangerous", "scout") is False
        assert is_blocked_combo("safe", "relationship") is False


class TestNumericToDanger:
    @pytest.mark.parametrize(
        "raw,expected",
        [(0, "safe"), (1, "moderate"), (2, "dangerous"), (3, "extreme"), ("2", "dangerous")],
    )
    def test_maps_numeric(self, raw, expected):
        assert numeric_to_danger(raw) == expected

    @pytest.mark.parametrize("raw", [None, ""])
    def test_missing_defaults_safe(self, raw):
        assert numeric_to_danger(raw) == "safe"

    def test_unknown_fails_closed(self):
        with pytest.raises(ValueError):
            numeric_to_danger(7)


class TestRollErrandRisk:
    def test_safe_destination_always_none(self):
        for roll in (1, 50, 100):
            assert roll_errand_risk("scout", "safe", "companion_kael", _FixedRng(roll)) == "none"

    def test_blocked_or_absent_cell_is_none(self):
        # extreme|social is absent from the table (a blocked combo) -> none.
        assert roll_errand_risk("social", "extreme", "companion_x", _FixedRng(1)) == "none"

    def test_extreme_scout_boundaries(self):
        # emergency 15, injury 40 (no reduction): 1-15 emergency, 16-55 injured, 56+ none.
        def roll(v):
            return roll_errand_risk("scout", "extreme", "companion_x", _FixedRng(v))

        assert roll(15) == "emergency"
        assert roll(16) == "injured"
        assert roll(55) == "injured"
        assert roll(56) == "none"

    def test_companion_injury_reduction(self):
        # dangerous|scout: emergency 5, injury 25. Kael -5 -> injured band 6-25.
        def roll(cid, v):
            return roll_errand_risk("scout", "dangerous", cid, _FixedRng(v))

        assert roll("companion_x", 30) == "injured"  # 5 + 25 = 30
        assert roll("companion_kael", 30) == "none"  # 5 + 20 = 25, so 30 -> none
        assert roll("companion_kael", 25) == "injured"
        assert roll("companion_kael", 5) == "emergency"  # emergency band unaffected

    def test_default_rng_returns_valid_outcome(self):
        assert roll_errand_risk("scout", "dangerous", "companion_kael") in {"none", "injured", "emergency"}
