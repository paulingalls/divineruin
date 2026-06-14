"""Resonance rules engine (story-001, M3.1) — pure, no IO.

Resonance is the hidden per-caster stat that measures how much the local Veil
fabric a caster has disturbed this encounter. It is a deterministic mechanic
(CLAUDE.md golden rule #3): the LLM decides *when* a spell is cast and *how* to
narrate the strain; this module calculates the numbers. The player never sees the
value (spec magic.md:98) — the DM narrates the *state*. The source multipliers,
the primal terrain table, the state thresholds, and the per-state damage-die/DC
modifiers are a small closed table, so they live as code constants (same call as
the durability rules engine) rather than DB-loaded content.

Every function reads and returns plain ints/dicts and never mutates its input.

Spec sources: docs/game_mechanics/game_mechanics_magic.md §Resonance System —
generation pseudocode (110-124), states (100-106), decay (126-131), primal terrain
table (71-80).

Decisions resolved by this story:
- resonance-generation-fn-name: the canonical public name is
  calculate_resonance_generated (milestone deliverable + the M3.3 cast_spell
  consumer); the spec pseudocode shorthand is resonance_generated — same function.
- resonance-primal-terrain-routing: source "primal" routes through
  PRIMAL_TERRAIN_TABLE, not the multiplier dict; the "normal" default is valid only
  for non-primal sources, so primal fails loud on an unknown/absent terrain.
- resonance-veythar-seam: divine_veythar_post_reveal (0.7) is reserved now per the
  spec pseudocode as the Phase-8 patron seam; it costs nothing as a data row today.

Consumers (later stories/milestones): persistence (story-002) stores the value the
state derives from; rest wiring (story-003) resets it; M3.3 cast_spell calls
calculate_resonance_generated and consumes get_state_modifiers for spell damage;
M3.4 wires the Human racial_modifier into apply_resonance_decay.
"""

import math
from typing import Literal

ResState = Literal["stable", "flickering", "overreach"]

# Magic source -> Resonance generation multiplier (spec 110-124). "primal" is
# absent on purpose: it is terrain-dependent and routes through PRIMAL_TERRAIN_TABLE.
# divine_veythar_post_reveal is the Phase-8 patron seam (compromised divine filter).
RESONANCE_GENERATION_MULTIPLIERS: dict[str, float] = {
    "arcane": 0.6,
    "divine": 0.3,
    "bard": 0.4,
    "divine_veythar_post_reveal": 0.7,
}

# Terrain -> primal Resonance multiplier (spec terrain table, 71-80). Primal magic
# draws on the health of the local environment: near-zero in ancient nature, high in
# Hollow-corrupted ground.
PRIMAL_TERRAIN_TABLE: dict[str, float] = {
    "ancient_forest": 0.1,
    "sacred_grove": 0.1,
    "healthy_natural": 0.2,
    "farmland": 0.3,
    "village": 0.4,
    "large_city": 0.5,
    "damaged": 0.6,
    "hollow_adjacent": 0.7,
    "hollow_corrupted": 0.8,
}

# Resonance state -> free combat modifiers (spec 100-106). Flickering grants +1
# damage die; Overreach grants +2 damage dice and +2 to spell DCs. M3.3 consumes
# these when resolving spell damage.
STATE_MODIFIERS: dict[ResState, dict[str, int]] = {
    "stable": {"damage_dice": 0, "dc": 0},
    "flickering": {"damage_dice": 1, "dc": 0},
    "overreach": {"damage_dice": 2, "dc": 2},
}


def calculate_resonance_generated(focus_cost: int, source: str, terrain: str = "normal") -> int:
    """Return the Resonance a cast generates: ceil(focus_cost * source_multiplier).

    Cantrips (focus_cost == 0) generate no Resonance (spec 112-113). Primal magic is
    terrain-dependent, so source "primal" looks the multiplier up in
    PRIMAL_TERRAIN_TABLE (the "normal" default is only valid for non-primal sources).
    Fails loud on a negative focus_cost, an unknown source, or an unknown primal terrain.
    """
    if focus_cost < 0:
        raise ValueError(f"focus_cost must be non-negative, got {focus_cost}")
    if focus_cost == 0:
        return 0

    if source == "primal":
        try:
            multiplier = PRIMAL_TERRAIN_TABLE[terrain]
        except KeyError:
            raise ValueError(f"unknown primal terrain {terrain!r}") from None
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
    bonus is a pure param; the call site (story-006) supplies it from the racial lookup. The
    default 0 is the canonical band, so existing callers are unchanged.
    """
    if current_resonance <= STABLE_MAX + flickering_bonus:
        return "stable"
    if current_resonance <= FLICKERING_MAX + flickering_bonus:
        return "flickering"
    return "overreach"


def apply_resonance_decay(current_resonance: int, racial_modifier: int = 0) -> int:
    """Return Resonance after one round of decay; never below 0 (spec 126-131).

    Standard decay is 1 per round. The Human racial (Adaptive Resonance) passes
    racial_modifier=1 to decay 2 per round — M3.4 wires that value from the racial
    table; this function only exposes the parameter.
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
