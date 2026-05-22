"""Companion-errand risk — pure functions, rolled by the async worker at resolution.

Risk is rolled once when the worker resolves an errand (async_worker.py), not at
dispatch: nothing observes the outcome before resolution, so the timing is
behaviorally identical, and keeping the roll here means it lives in exactly one
place (ADR 0006). The TS server (apps/server/src/errand_risk.ts) keeps only the
dispatch-time blocked-combo + danger-level gate and no longer rolls risk.

Tables track game_mechanics_core.md §Companion Risk (L887-892); both languages
conformance-pin BLOCKED_DANGER_COMBOS against that spec doc (the oracle).
"""

from __future__ import annotations

import random

# Spec matrix — game_mechanics_core.md §Companion Risk L887-892. Cells absent here
# are N/A and blocked via BLOCKED_DANGER_COMBOS. Keyed "{danger}|{errand}".
ERRAND_RISK_TABLE: dict[str, dict[str, int]] = {
    "safe|scout": {"injury_pct": 0, "emergency_pct": 0},
    "safe|social": {"injury_pct": 0, "emergency_pct": 0},
    "safe|acquire": {"injury_pct": 0, "emergency_pct": 0},
    "safe|relationship": {"injury_pct": 0, "emergency_pct": 0},
    "moderate|scout": {"injury_pct": 10, "emergency_pct": 0},
    "moderate|social": {"injury_pct": 0, "emergency_pct": 0},
    "moderate|acquire": {"injury_pct": 10, "emergency_pct": 0},
    "moderate|relationship": {"injury_pct": 0, "emergency_pct": 0},
    "dangerous|scout": {"injury_pct": 25, "emergency_pct": 5},
    "dangerous|social": {"injury_pct": 0, "emergency_pct": 0},
    "dangerous|acquire": {"injury_pct": 20, "emergency_pct": 0},
    "extreme|scout": {"injury_pct": 40, "emergency_pct": 15},
}

# Injury risk reduction per companion (e.g. Kael's veteran survival instincts).
COMPANION_INJURY_REDUCTION: dict[str, int] = {
    "companion_kael": 5,
}

# Blocked (danger_level, errand_type) combos — the spec's N/A cells (L887-892).
BLOCKED_DANGER_COMBOS: frozenset[str] = frozenset(
    {
        "dangerous|relationship",
        "extreme|relationship",
        "extreme|social",
        "extreme|acquire",
    }
)

_NUMERIC_DANGER = {"0": "safe", "1": "moderate", "2": "dangerous", "3": "extreme"}


def is_blocked_combo(danger_level: str, errand_type: str) -> bool:
    """True when this (danger, errand) pair is a spec N/A cell."""
    return f"{danger_level}|{errand_type}" in BLOCKED_DANGER_COMBOS


def numeric_to_danger(raw: int | str | None) -> str:
    """Map a location's numeric danger_level (0-3) to a danger label.

    None/empty default to "safe". Unknown values fail closed (raise) — a typo in
    seed data must not silently downgrade a dangerous destination.
    """
    if raw is None or raw == "":
        return "safe"
    label = _NUMERIC_DANGER.get(str(raw))
    if label is None:
        raise ValueError(f"numeric_to_danger: unknown danger_level value {raw!r}")
    return label


def roll_errand_risk(
    errand_type: str,
    danger_level: str,
    companion_id: str,
    rng: random.Random | None = None,
) -> str:
    """Roll the errand injury outcome: "none" | "injured" | "emergency".

    d100 against the spec table, minus the companion's injury reduction. Safe or
    absent cells always return "none".
    """
    entry = ERRAND_RISK_TABLE.get(f"{danger_level}|{errand_type}")
    if not entry or (entry["injury_pct"] == 0 and entry["emergency_pct"] == 0):
        return "none"

    roll = (rng or random.Random()).randint(1, 100)
    reduction = COMPANION_INJURY_REDUCTION.get(companion_id, 0)
    effective_injury = max(0, entry["injury_pct"] - reduction)

    if roll <= entry["emergency_pct"]:
        return "emergency"
    if roll <= entry["emergency_pct"] + effective_injury:
        return "injured"
    return "none"
