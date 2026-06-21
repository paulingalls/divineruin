"""Unit coverage for the pure encounter-budget validator (M4.7, story-004).

The module is pure: every test builds a plain list of role-tagged enemy dicts and a
player level, then asserts on the returned report — no DB, no RNG, no combat state. The
validator is INFORMATIONAL: it returns a report and flags violations; it never blocks
combat. Budget weights + difficulty thresholds + allocation rules come from
docs/game_mechanics/game_mechanics_encounter_roles.md (L209-234).
"""

import pytest

from encounter_budget import calculate_encounter_budget


def _enemies(*roles: str) -> list[dict]:
    """Minimal role-tagged enemy dicts (the validator reads only the ``role`` field)."""
    return [{"id": f"e{i}", "role": role} for i, role in enumerate(roles)]


# --- budget math: Minions weighted 0.5, Named ignored -----------------------------------


def test_budget_sums_role_costs():
    # 1 Elite (2.0) + 1 Standard (1.0) + 2 Minions (1.0) = 4.0
    report = calculate_encounter_budget(_enemies("elite", "standard", "minion", "minion"), player_level=7)
    assert report["total"] == 4.0


def test_minions_weighted_half():
    # 6 Minions = 3.0 (the L3 wolf-pack worked example).
    report = calculate_encounter_budget(_enemies(*(["minion"] * 6)), player_level=3)
    assert report["total"] == 3.0


def test_named_enemies_do_not_add_to_total():
    # Named ignores budget (D81): a Named + a Standard costs only the Standard's 1.0.
    report = calculate_encounter_budget(_enemies("named", "standard"), player_level=5)
    assert report["total"] == 1.0


def test_empty_encounter_is_zero_and_unflagged():
    report = calculate_encounter_budget([], player_level=1)
    assert report["total"] == 0.0
    assert report["too_many_bosses"] is False
    assert report["all_minion"] is False
    assert report["over_budget"] is False


# --- level-band threshold selection ------------------------------------------------------


@pytest.mark.parametrize(
    "level,band,thresholds",
    [
        (1, "1-2", {"standard": 2.0, "tough": 3.0, "boss": 4.0}),
        (2, "1-2", {"standard": 2.0, "tough": 3.0, "boss": 4.0}),
        (3, "3-4", {"standard": 3.0, "tough": 4.5, "boss": 5.0}),
        (4, "3-4", {"standard": 3.0, "tough": 4.5, "boss": 5.0}),
        (5, "5-8", {"standard": 4.0, "tough": 6.0, "boss": 7.0}),
        (8, "5-8", {"standard": 4.0, "tough": 6.0, "boss": 7.0}),
        (9, "9-14", {"standard": 5.0, "tough": 7.5, "boss": 9.0}),
        (14, "9-14", {"standard": 5.0, "tough": 7.5, "boss": 9.0}),
        (15, "15-20", {"standard": 6.0, "tough": 9.0, "boss": 11.0}),
        (20, "15-20", {"standard": 6.0, "tough": 9.0, "boss": 11.0}),
    ],
)
def test_level_band_thresholds(level, band, thresholds):
    report = calculate_encounter_budget([], player_level=level)
    assert report["level_band"] == band
    assert report["thresholds"] == thresholds


@pytest.mark.parametrize("level", [0, -1, 21, 100])
def test_out_of_range_level_fails_loud(level):
    with pytest.raises(ValueError, match="player_level"):
        calculate_encounter_budget([], player_level=level)


def test_unknown_role_fails_loud():
    with pytest.raises(ValueError, match="role"):
        calculate_encounter_budget([{"id": "x", "role": "lieutenant"}], player_level=3)


# --- over_budget flag (ceiling = the boss-encounter threshold) ---------------------------


def test_within_boss_threshold_is_not_over_budget():
    # L3 boss-encounter ceiling is 5.0; 1 Boss (4.0) + 2 Minions (1.0) = 5.0 sits at the line.
    report = calculate_encounter_budget(_enemies("boss", "minion", "minion"), player_level=3)
    assert report["total"] == 5.0
    assert report["over_budget"] is False


def test_over_boss_threshold_sets_over_budget():
    # L1 ceiling is 4.0; 2 Elites (4.0) + 1 Standard (1.0) = 5.0 exceeds it.
    report = calculate_encounter_budget(_enemies("elite", "elite", "standard"), player_level=1)
    assert report["total"] == 5.0
    assert report["over_budget"] is True


# --- too_many_bosses (D80: at most one Boss) ---------------------------------------------


def test_single_boss_is_allowed():
    report = calculate_encounter_budget(_enemies("boss", "minion"), player_level=7)
    assert report["too_many_bosses"] is False


def test_two_bosses_flags_too_many_bosses():
    report = calculate_encounter_budget(_enemies("boss", "boss"), player_level=15)
    assert report["too_many_bosses"] is True


# --- all_minion (Minions need a non-Minion anchor) ---------------------------------------


def test_all_minion_composition_is_flagged():
    report = calculate_encounter_budget(_enemies("minion", "minion", "minion"), player_level=3)
    assert report["all_minion"] is True


def test_minions_with_a_standard_anchor_not_flagged():
    report = calculate_encounter_budget(_enemies("minion", "minion", "standard"), player_level=3)
    assert report["all_minion"] is False


def test_minions_with_a_named_anchor_not_flagged():
    # A Named counts as a non-Minion anchor even though it carries no budget cost.
    report = calculate_encounter_budget(_enemies("minion", "minion", "named"), player_level=5)
    assert report["all_minion"] is False


def test_no_minions_never_flags_all_minion():
    report = calculate_encounter_budget(_enemies("standard", "elite"), player_level=5)
    assert report["all_minion"] is False
