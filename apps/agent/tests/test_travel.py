"""Tests for the pure travel resolver (M4.6b / story-001).

Pure functions, no DB/RNG/fixtures — the caller supplies the navigation roll_total,
mirroring test_social_resolution.py. Spec: docs/game_mechanics/game_mechanics_combat.md
§Travel and Exploration (L852-969).
"""

import pytest

import travel

# --- Travel mode table (spec L852-860) ---


def test_three_spec_modes_present():
    assert set(travel.TRAVEL_MODE_NAMES) == {"compressed", "scenic", "dangerous"}


def test_encounter_rate_orders_compressed_below_scenic_below_dangerous():
    def rate(m):
        return travel.travel_mode_params(m).encounter_rate

    assert rate("compressed") < rate("scenic") < rate("dangerous")
    assert rate("compressed") == 0.0  # montage, no encounters


def test_time_multiplier_orders_compressed_below_scenic_below_dangerous():
    def mult(m):
        return travel.travel_mode_params(m).time_multiplier

    assert mult("compressed") < mult("scenic") < mult("dangerous")


def test_foraging_available_only_on_scenic_and_dangerous():
    assert travel.travel_mode_params("compressed").foraging_available is False
    assert travel.travel_mode_params("scenic").foraging_available is True
    assert travel.travel_mode_params("dangerous").foraging_available is True


def test_unknown_mode_fails_loud():
    with pytest.raises(ValueError, match="unknown travel mode"):
        travel.travel_mode_params("teleport")


# --- Navigation DC table (spec L922-929) ---


def test_navigation_dc_matches_spec_terrain_table():
    assert travel.navigation_dc("established_road") is None  # auto-success
    assert travel.navigation_dc("known_trail") == 8
    assert travel.navigation_dc("unmarked_wilderness") == 12
    assert travel.navigation_dc("dense_forest") == 14
    assert travel.navigation_dc("underground") == 16
    assert travel.navigation_dc("hollow_corrupted") == 18


def test_unknown_terrain_fails_loud():
    with pytest.raises(ValueError, match="unknown terrain"):
        travel.navigation_dc("the_moon")


# --- resolve_travel_segment: established road auto-success (spec L924) ---


def test_established_road_auto_succeeds_regardless_of_roll():
    result = travel.resolve_travel_segment(mode="compressed", terrain="established_road", roll_total=1)
    assert result.success is True
    assert result.dc is None
    assert result.margin is None
    assert result.wrong_area is False
    # compressed montage time: base * 0.5
    assert result.time_cost == pytest.approx(4 * travel.travel_mode_params("compressed").time_multiplier)


def test_established_road_carries_mode_encounter_and_foraging():
    result = travel.resolve_travel_segment(mode="scenic", terrain="established_road", roll_total=10)
    assert result.encounter_rate == travel.travel_mode_params("scenic").encounter_rate
    assert result.foraging_available is True


# --- resolve_travel_segment: navigation success / failure (spec L922-929) ---


def test_roll_at_or_above_dc_succeeds_without_wrong_area():
    result = travel.resolve_travel_segment(mode="dangerous", terrain="unmarked_wilderness", roll_total=12)
    assert result.dc == 12
    assert result.margin == 0
    assert result.success is True
    assert result.wrong_area is False


def test_failure_in_unmarked_wilderness_gets_lost_and_costs_time():
    clean = travel.resolve_travel_segment(mode="scenic", terrain="unmarked_wilderness", roll_total=12)
    lost = travel.resolve_travel_segment(mode="scenic", terrain="unmarked_wilderness", roll_total=5)
    assert lost.success is False
    assert lost.wrong_area is True
    assert lost.time_cost > clean.time_cost  # failure adds a time penalty


def test_known_trail_failure_is_minor_detour_not_wrong_area():
    detour = travel.resolve_travel_segment(mode="scenic", terrain="known_trail", roll_total=3)
    assert detour.success is False
    assert detour.wrong_area is False  # minor detour, not lost (spec L925)


@pytest.mark.parametrize("terrain", ["dense_forest", "underground", "hollow_corrupted"])
def test_deep_terrain_failure_sets_wrong_area(terrain):
    result = travel.resolve_travel_segment(mode="dangerous", terrain=terrain, roll_total=1)
    assert result.success is False
    assert result.wrong_area is True


# --- Exhaustion delta (spec L938-951) ---


def test_clean_non_forced_success_has_zero_exhaustion():
    result = travel.resolve_travel_segment(mode="scenic", terrain="known_trail", roll_total=20)
    assert result.exhaustion_delta == 0


def test_forced_march_accumulates_one_stack_per_extra_four_hours():
    eight = travel.resolve_travel_segment(
        mode="dangerous", terrain="known_trail", roll_total=20, base_hours=8, forced_march=True
    )
    twelve = travel.resolve_travel_segment(
        mode="dangerous", terrain="known_trail", roll_total=20, base_hours=12, forced_march=True
    )
    sixteen = travel.resolve_travel_segment(
        mode="dangerous", terrain="known_trail", roll_total=20, base_hours=16, forced_march=True
    )
    assert eight.exhaustion_delta == 0  # at the 8h threshold, no stack yet
    assert twelve.exhaustion_delta == 1
    assert sixteen.exhaustion_delta == 2


def test_forced_march_flag_off_never_exhausts_from_hours():
    result = travel.resolve_travel_segment(
        mode="scenic", terrain="known_trail", roll_total=20, base_hours=16, forced_march=False
    )
    assert result.exhaustion_delta == 0


def test_underground_lost_failure_adds_exhaustion():
    # spec L928: seriously lost underground exhausts a ration (an exhaustion bump)
    result = travel.resolve_travel_segment(mode="dangerous", terrain="underground", roll_total=1)
    assert result.exhaustion_delta >= 1


# --- Dramatic verdict (delegated to the M4.5 SSOT) ---


def test_natural_twenty_is_dramatic():
    result = travel.resolve_travel_segment(mode="dangerous", terrain="hollow_corrupted", roll_total=23, raw_die=20)
    assert result.dramatic is True
    assert result.context == "natural_20"


def test_natural_one_is_dramatic():
    result = travel.resolve_travel_segment(mode="dangerous", terrain="hollow_corrupted", roll_total=4, raw_die=1)
    assert result.dramatic is True
    assert result.context == "natural_1"


def test_razor_thin_margin_is_dramatic():
    result = travel.resolve_travel_segment(mode="dangerous", terrain="unmarked_wilderness", roll_total=12, raw_die=8)
    assert result.margin == 0
    assert result.dramatic is True
    assert result.context == "razor_thin"


def test_ordinary_clear_pass_is_not_dramatic():
    result = travel.resolve_travel_segment(mode="scenic", terrain="known_trail", roll_total=20, raw_die=15)
    assert result.dramatic is False
    assert result.context == ""


# --- Determinism (pure: no IO/RNG) ---


def test_same_inputs_yield_identical_result():
    first = travel.resolve_travel_segment(mode="dangerous", terrain="dense_forest", roll_total=10, raw_die=6)
    second = travel.resolve_travel_segment(mode="dangerous", terrain="dense_forest", roll_total=10, raw_die=6)
    assert first == second


def test_unknown_mode_in_resolve_fails_loud():
    with pytest.raises(ValueError, match="unknown travel mode"):
        travel.resolve_travel_segment(mode="warp", terrain="known_trail", roll_total=10)
