"""Tests for the pure Resonance rules engine (story-001, M3.1).

Resonance is a closed-table deterministic mechanic (CLAUDE.md golden rule #3):
the source multipliers, the primal terrain table, the state thresholds, and the
per-state damage-die/DC modifiers are code constants, not DB-loaded content (same
call as the durability rules engine). No IO — every function reads/returns plain
ints/dicts, so these are plain unit tests with no fixtures or pool.

Spec sources: docs/game_mechanics/game_mechanics_magic.md §Resonance System
generation pseudocode (110-124), states (100-106), decay (126-131), primal terrain
table (71-80).

Decisions recorded by this story:
- resonance-generation-fn-name: canonical name is calculate_resonance_generated
  (milestone deliverable + M3.3 cast_spell consumer); spec shorthand is resonance_generated.
- resonance-primal-terrain-routing: source "primal" routes through PRIMAL_TERRAIN_TABLE;
  "normal" default is non-primal-only; primal fails loud on unknown terrain.
- resonance-veythar-seam: divine_veythar_post_reveal 0.7 reserved now (Phase-8 patron seam).
"""

import pytest

import resonance

# --- calculate_resonance_generated: source multipliers (spec 110-124) ---------


@pytest.mark.parametrize(
    "focus,source,expected",
    [
        (5, "arcane", 3),  # ceil(5 * 0.6) = ceil(3.0) = 3
        (1, "arcane", 1),  # ceil(0.6) = 1
        (10, "divine", 3),  # ceil(10 * 0.3) = 3
        (1, "divine", 1),  # ceil(0.3) = 1
        (5, "bard", 2),  # ceil(5 * 0.4) = 2
        (10, "divine_veythar_post_reveal", 7),  # ceil(10 * 0.7) = 7 (Phase-8 seam)
    ],
)
def test_generation_per_source(focus, source, expected):
    assert resonance.calculate_resonance_generated(focus, source) == expected


@pytest.mark.parametrize("source", ["arcane", "divine", "bard", "primal"])
def test_cantrip_generates_zero_for_every_source(source):
    # focus_cost == 0 early-return (spec 112-113); terrain irrelevant for the 0 path.
    assert resonance.calculate_resonance_generated(0, source, "ancient_forest") == 0


def test_generation_unknown_source_fails_loud():
    with pytest.raises(ValueError):
        resonance.calculate_resonance_generated(5, "psionic")


def test_generation_negative_focus_fails_loud():
    # A negative focus_cost would yield negative Resonance (ceil(-5 * 0.6) = -3),
    # violating the Resonance >= 0 invariant — fail loud like durability's negative hits.
    with pytest.raises(ValueError):
        resonance.calculate_resonance_generated(-5, "arcane")


# --- primal terrain routing (spec 71-80) -------------------------------------


@pytest.mark.parametrize(
    "terrain,expected",
    [
        ("ancient_forest", 1),  # ceil(5 * 0.1) = 1
        ("sacred_grove", 1),  # ceil(5 * 0.1) = 1
        ("healthy_natural", 1),  # ceil(5 * 0.2) = 1
        ("farmland", 2),  # ceil(5 * 0.3) = 2
        ("village", 2),  # ceil(5 * 0.4) = 2
        ("large_city", 3),  # ceil(5 * 0.5) = 3
        ("damaged", 3),  # ceil(5 * 0.6) = 3
        ("hollow_adjacent", 4),  # ceil(5 * 0.7) = 4
        ("hollow_corrupted", 4),  # ceil(5 * 0.8) = 4
    ],
)
def test_primal_generation_by_terrain(terrain, expected):
    assert resonance.calculate_resonance_generated(5, "primal", terrain) == expected


def test_primal_unknown_terrain_fails_loud():
    with pytest.raises(ValueError):
        resonance.calculate_resonance_generated(5, "primal", "moon")


def test_primal_default_normal_terrain_fails_loud():
    # "normal" is the non-primal default; primal must name a real terrain.
    with pytest.raises(ValueError):
        resonance.calculate_resonance_generated(5, "primal")


# --- get_resonance_state thresholds (spec 100-106) ---------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, "stable"),
        (4, "stable"),
        (5, "flickering"),
        (8, "flickering"),
        (9, "overreach"),
        (20, "overreach"),
    ],
)
def test_resonance_state_thresholds(value, expected):
    assert resonance.get_resonance_state(value) == expected


# --- Thessyn flickering-threshold shift (M3.4 story-003, spec 270-276) --------
# Deep Adaptation: +1 to the Flickering threshold shifts the band 5-8 -> 6-9 (stable up to 5,
# overreach at 10+). The bonus is a pure param; story-006 supplies it from the racial lookup.


@pytest.mark.parametrize(
    "value,expected",
    [
        (4, "stable"),
        (5, "stable"),  # shifted: 5 is now stable (was flickering)
        (6, "flickering"),
        (9, "flickering"),  # shifted: 9 is now flickering (was overreach)
        (10, "overreach"),
    ],
)
def test_resonance_state_with_thessyn_flickering_bonus(value, expected):
    assert resonance.get_resonance_state(value, flickering_bonus=1) == expected


def test_flickering_bonus_defaults_to_zero_unchanged_bands():
    # Regression guard: the default (no bonus) keeps the canonical 4/8 boundary.
    assert resonance.get_resonance_state(4) == "stable"
    assert resonance.get_resonance_state(5) == "flickering"
    assert resonance.get_resonance_state(9) == "overreach"


# --- apply_resonance_decay (spec 126-131) ------------------------------------


def test_decay_default_minus_one():
    assert resonance.apply_resonance_decay(7) == 6


def test_decay_human_modifier_minus_two():
    assert resonance.apply_resonance_decay(7, racial_modifier=1) == 5


def test_decay_floors_at_zero():
    assert resonance.apply_resonance_decay(1, racial_modifier=1) == 0  # 1 - 2 -> 0


def test_decay_at_zero_stays_zero():
    assert resonance.apply_resonance_decay(0) == 0


# --- apply_primal_reduction (M3.4 story-003, Korath earth-anchored, spec 254-260) ---
# Korath generates -1 Resonance on primal spells (floor 0). Pure generation-modifier mirroring
# veil_ward.halve_generation; the reduction value comes from the racial lookup (story-001).


def test_primal_reduction_subtracts():
    assert resonance.apply_primal_reduction(5, 1) == 4


def test_primal_reduction_floors_at_zero():
    assert resonance.apply_primal_reduction(0, 1) == 0
    assert resonance.apply_primal_reduction(1, 3) == 0  # would be -2 -> floored


def test_primal_reduction_rejects_negative_generated():
    with pytest.raises(ValueError, match="generated"):
        resonance.apply_primal_reduction(-1, 1)


def test_primal_reduction_rejects_negative_reduction():
    with pytest.raises(ValueError, match="reduction"):
        resonance.apply_primal_reduction(5, -1)


# --- get_state_modifiers (spec 100-106) --------------------------------------


@pytest.mark.parametrize(
    "state,damage_dice,dc",
    [("stable", 0, 0), ("flickering", 1, 0), ("overreach", 2, 2)],
)
def test_state_modifiers(state, damage_dice, dc):
    mods = resonance.get_state_modifiers(state)
    assert mods == {"damage_dice": damage_dice, "dc": dc}


def test_state_modifiers_unknown_state_fails_loud():
    with pytest.raises(ValueError):
        resonance.get_state_modifiers("ascendant")  # type: ignore[arg-type]


def test_state_modifiers_returns_copy_not_constant():
    mods = resonance.get_state_modifiers("overreach")
    mods["dc"] = 99  # mutating the result must not corrupt the module constant
    assert resonance.get_state_modifiers("overreach") == {"damage_dice": 2, "dc": 2}
