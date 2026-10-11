"""Pure Resonance generation, state, decay and racial reduction mechanics."""

import math
from typing import Literal

from terrain import resonance_base

ResState = Literal["stable", "flickering", "overreach"]

# The post-reveal Veythar multiplier reserves the compromised divine-filter seam.
RESONANCE_GENERATION_MULTIPLIERS: dict[str, float] = {
    "arcane": 0.6,
    "divine": 0.3,
    "bard": 0.4,
    "divine_veythar_post_reveal": 0.7,
}

# Resonance state -> free combat modifiers (spec 100-106). Flickering grants +1
# damage die; Overreach grants +2 damage dice and +2 to spell DCs. M3.3 consumes
# these when resolving spell damage.
STATE_MODIFIERS: dict[ResState, dict[str, int]] = {
    "stable": {"damage_dice": 0, "dc": 0},
    "flickering": {"damage_dice": 1, "dc": 0},
    "overreach": {"damage_dice": 2, "dc": 2},
}


def calculate_resonance_generated(focus_cost: int, source: str, terrain: str | None) -> int:
    """Return ceil(Focus * multiplier); primal requires a supported location terrain."""
    if focus_cost < 0:
        raise ValueError(f"focus_cost must be non-negative, got {focus_cost}")
    if source == "primal":
        multiplier = resonance_base(terrain)  # type: ignore[arg-type]
    else:
        try:
            multiplier = RESONANCE_GENERATION_MULTIPLIERS[source]
        except KeyError:
            raise ValueError(f"unknown magic source {source!r}") from None
    return math.ceil(focus_cost * multiplier)


# Base state thresholds (spec 100-106): stable 0-4, flickering 5-8, overreach 9+. The Thessyn
# racial (Deep Adaptation, M3.4) shifts both up by its flickering_bonus.
STABLE_MAX = 4
FLICKERING_MAX = 8


def get_resonance_state(current_resonance: int, flickering_bonus: int = 0) -> ResState:
    """Classify a Resonance value: stable 0-4, flickering 5-8, overreach 9+ (spec 100-106).

    flickering_bonus (Thessyn Deep Adaptation, spec 270-276) shifts both thresholds up,
    moving the flickering band 5-8 -> 6-9 at bonus=1 (stable up to 5, overreach at 10+). The
    bonus is a pure param; the call site (story-006) supplies it from
    racial_resonance.get_racial_resonance_modifier(race, "flickering_threshold_bonus") (the
    engine param stays content-agnostic, hence the shorter name). The default 0 is the
    canonical band, so existing callers are unchanged.
    """
    if current_resonance <= STABLE_MAX + flickering_bonus:
        return "stable"
    if current_resonance <= FLICKERING_MAX + flickering_bonus:
        return "flickering"
    return "overreach"


def apply_resonance_decay(current_resonance: int, racial_modifier: int = 0) -> int:
    """Return Resonance after one round of decay; never below 0 (spec 126-131).

    Standard decay is 1 per round. The Human racial (Adaptive Resonance) passes
    racial_modifier=1 to decay 2 per round. M3.5 story-010 is the live consumer:
    spell_casting._cast_spell_impl calls this cast-paced (one round shed per real
    cast), passing the Human modifier from the racial table.
    """
    return max(0, current_resonance - (1 + racial_modifier))


def apply_primal_reduction(generated: int, reduction: int) -> int:
    """Reduce the Resonance a primal cast generates, floored at 0 (Korath Earth-anchored, spec 254-260).

    Pure generation-modifier, the sibling of veil_ward.halve_generation. The Korath-on-primal(-on-
    earth/stone) gating lives at the call site (story-006); this fn is the mechanic, and `reduction`
    comes from racial_resonance.get_racial_resonance_modifier("korath", "primal_reduction"). Fails
    loud on a negative input — generation and the racial reduction are both non-negative.
    """
    if generated < 0:
        raise ValueError(f"generated must be non-negative, got {generated}")
    if reduction < 0:
        raise ValueError(f"reduction must be non-negative, got {reduction}")
    return max(0, generated - reduction)


def get_state_modifiers(state: ResState) -> dict[str, int]:
    """Return a copy of the damage-die/DC modifiers for a Resonance state; fail loud on unknown."""
    try:
        return dict(STATE_MODIFIERS[state])
    except KeyError:
        raise ValueError(f"unknown resonance state {state!r}") from None
