"""Tests for XP thresholds and level-up mechanics."""

from rules_engine import (
    XP_FOR_LEVEL,
    check_level_up,
)

# --- check_level_up ---


class TestCheckLevelUp:
    def test_no_level_up(self):
        result = check_level_up(current_xp=0, xp_gained=100, current_level=1)
        assert result.new_xp == 100
        assert result.new_level == 1
        assert result.leveled_up is False
        assert result.levels_gained == 0

    def test_level_up_to_2(self):
        # Canonical: L2 threshold = 200 cumulative
        result = check_level_up(current_xp=100, xp_gained=100, current_level=1)
        assert result.new_xp == 200
        assert result.new_level == 2
        assert result.leveled_up is True
        assert result.levels_gained == 1

    def test_exact_threshold(self):
        # Canonical: L2 = 200
        result = check_level_up(current_xp=0, xp_gained=200, current_level=1)
        assert result.new_level == 2

    def test_multi_level_up(self):
        # Canonical: L5 = 1050, award enough to reach L5
        result = check_level_up(current_xp=0, xp_gained=1050, current_level=1)
        assert result.new_level == 5
        assert result.levels_gained == 4

    def test_max_level_cap(self):
        # Canonical: L20 = 11250
        result = check_level_up(current_xp=11250, xp_gained=50000, current_level=20)
        assert result.new_xp == 61250
        assert result.new_level == 20
        assert result.leveled_up is False

    def test_xp_table_is_monotonic(self):
        for lvl in range(2, 21):
            assert XP_FOR_LEVEL[lvl] > XP_FOR_LEVEL[lvl - 1]

    def test_level_1_starts_at_zero(self):
        assert XP_FOR_LEVEL[1] == 0

    def test_xp_table_matches_canonical(self):
        """Verify XP table matches game_mechanics_core.md canonical values."""
        canonical = {
            1: 0,
            2: 200,
            3: 450,
            4: 750,
            5: 1050,
            6: 1450,
            7: 1900,
            8: 2400,
            9: 2900,
            10: 3450,
            11: 4050,
            12: 4650,
            13: 5300,
            14: 6000,
            15: 6750,
            16: 7550,
            17: 8400,
            18: 9300,
            19: 10250,
            20: 11250,
        }
        assert canonical == XP_FOR_LEVEL

    def test_xp_table_has_20_levels(self):
        assert len(XP_FOR_LEVEL) == 20

    # --- Attribute points ---

    def test_level_4_grants_attribute_points(self):
        # L3 → L4: attribute increase level
        result = check_level_up(current_xp=450, xp_gained=300, current_level=3)
        assert result.new_level == 4
        assert result.attribute_points == 2

    def test_level_3_no_attribute_points(self):
        # L2 → L3: not an attribute increase level
        result = check_level_up(current_xp=200, xp_gained=250, current_level=2)
        assert result.new_level == 3
        assert result.attribute_points == 0

    def test_no_level_up_no_attribute_points(self):
        result = check_level_up(current_xp=0, xp_gained=100, current_level=1)
        assert result.attribute_points == 0

    def test_multi_level_accumulates_attribute_points(self):
        # L1 → L8: crosses L4 (+2) and L8 (+2) = 4 total
        result = check_level_up(current_xp=0, xp_gained=2400, current_level=1)
        assert result.new_level == 8
        assert result.attribute_points == 4

    def test_all_attribute_increase_levels(self):
        # L1 → L20: crosses L4, L8, L12, L16, L20 = 10 total
        result = check_level_up(current_xp=0, xp_gained=11250, current_level=1)
        assert result.new_level == 20
        assert result.attribute_points == 10

    # --- Specialization fork ---

    def test_level_5_specialization_fork(self):
        # L4 → L5: specialization level
        result = check_level_up(current_xp=750, xp_gained=300, current_level=4)
        assert result.new_level == 5
        assert result.specialization_fork is True

    def test_level_4_no_fork(self):
        # L3 → L4: not specialization level
        result = check_level_up(current_xp=450, xp_gained=300, current_level=3)
        assert result.new_level == 4
        assert result.specialization_fork is False

    def test_multi_level_includes_fork(self):
        # L1 → L8: crosses L5, so fork is True
        result = check_level_up(current_xp=0, xp_gained=2400, current_level=1)
        assert result.new_level == 8
        assert result.specialization_fork is True

    def test_past_fork_no_flag(self):
        # L6 → L8: already past L5, fork is False
        result = check_level_up(current_xp=1450, xp_gained=950, current_level=6)
        assert result.new_level == 8
        assert result.specialization_fork is False


class TestLevelUpE2E:
    """E2E acceptance criteria: XP awards produce correct level-up rewards."""

    def test_cross_l4_threshold(self):
        # Award XP to go from L1 to L4 (cumulative 750)
        result = check_level_up(current_xp=0, xp_gained=750, current_level=1)
        assert result.new_level == 4
        assert result.attribute_points == 2
        assert result.specialization_fork is False

    def test_cross_l5_threshold(self):
        # Award XP to go from L4 to L5 (cumulative 1050)
        result = check_level_up(current_xp=750, xp_gained=300, current_level=4)
        assert result.new_level == 5
        assert result.attribute_points == 0
        assert result.specialization_fork is True

    def test_l1_to_l5_gets_both(self):
        # Award XP to go from L1 to L5 (cumulative 1050)
        result = check_level_up(current_xp=0, xp_gained=1050, current_level=1)
        assert result.new_level == 5
        assert result.attribute_points == 2  # from L4
        assert result.specialization_fork is True  # from L5
        assert result.levels_gained == 4
