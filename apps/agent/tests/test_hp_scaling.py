"""Tests for HP scaling — archetype-based HP formula.

calculate_hp is pure math (unchanged). calculate_max_hp now derives base/growth
from the chassis SSOT via get_archetype_chassis (seeded by the autouse
seed_archetypes conftest fixture from content/archetypes.json). The per-archetype
HP expectations below are hardcoded from the historically-correct values — an
independent anchor pinning the chassis to those numbers now that the legacy
ARCHETYPE_HP_CONFIG constant is gone.
"""

import pytest
from sample_fixtures import GUILD_PLAYER, SAMPLE_PLAYER

from archetypes import get_archetype_chassis
from hp_scaling import calculate_hp, calculate_max_hp

# id -> (hp_base, hp_growth, hp_category), the legacy ARCHETYPE_HP_CONFIG values.
EXPECTED_HP = {
    "warrior": (12, 5, "martial"),
    "guardian": (12, 5, "martial"),
    "skirmisher": (12, 5, "martial"),
    "druid": (10, 4, "primal_divine"),
    "beastcaller": (10, 4, "primal_divine"),
    "warden": (10, 4, "primal_divine"),
    "cleric": (10, 4, "primal_divine"),
    "paladin": (10, 4, "primal_divine"),
    "oracle": (10, 4, "primal_divine"),
    "marshal": (10, 4, "primal_divine"),
    "mage": (8, 3, "arcane_shadow"),
    "artificer": (8, 3, "arcane_shadow"),
    "seeker": (8, 3, "arcane_shadow"),
    "rogue": (8, 3, "arcane_shadow"),
    "spy": (8, 3, "arcane_shadow"),
    "whisper": (8, 3, "arcane_shadow"),
    "bard": (8, 3, "arcane_shadow"),
    "diplomat": (8, 3, "arcane_shadow"),
}


class TestSampleFixtureArchetypes:
    """Shared player fixtures must carry a valid archetype, or any HP/leveling
    test that reuses them raises ValueError in calculate_max_hp."""

    @pytest.mark.parametrize("player", [SAMPLE_PLAYER, GUILD_PLAYER], ids=["sample", "guild"])
    def test_class_is_a_known_archetype(self, player):
        # get_archetype_chassis raises ValueError if the class is unknown.
        assert get_archetype_chassis(player["class"]).id == player["class"]


class TestArchetypeChassisHP:
    """The 18 chassis carry the historically-correct HP base/growth/category."""

    def test_all_18_present_with_expected_hp(self):
        for aid, (base, growth, category) in EXPECTED_HP.items():
            c = get_archetype_chassis(aid)
            assert (c.hp_base, c.hp_growth, c.hp_category) == (base, growth, category), aid

    def test_martial_category(self):
        for name in ("warrior", "guardian", "skirmisher"):
            c = get_archetype_chassis(name)
            assert c.hp_category == "martial" and c.hp_base == 12 and c.hp_growth == 5

    def test_primal_divine_category(self):
        for name in ("druid", "beastcaller", "warden", "cleric", "paladin", "oracle", "marshal"):
            c = get_archetype_chassis(name)
            assert c.hp_category == "primal_divine" and c.hp_base == 10 and c.hp_growth == 4

    def test_arcane_shadow_category(self):
        for name in ("mage", "artificer", "seeker", "rogue", "spy", "whisper", "bard", "diplomat"):
            c = get_archetype_chassis(name)
            assert c.hp_category == "arcane_shadow" and c.hp_base == 8 and c.hp_growth == 3


class TestCalculateHP:
    """Verify calculate_hp against the doc table (game_mechanics_core.md:528-541)."""

    # --- CON +1 (round-half-up: (1+1)//2 = 1 per level) ---

    def test_martial_l1_con1(self):
        assert calculate_hp(level=1, base_hp=12, growth=5, con_mod=1) == 13

    def test_martial_l10_con1(self):
        assert calculate_hp(level=10, base_hp=12, growth=5, con_mod=1) == 67

    def test_martial_l20_con1(self):
        assert calculate_hp(level=20, base_hp=12, growth=5, con_mod=1) == 127

    def test_primal_divine_l1_con1(self):
        assert calculate_hp(level=1, base_hp=10, growth=4, con_mod=1) == 11

    def test_primal_divine_l10_con1(self):
        assert calculate_hp(level=10, base_hp=10, growth=4, con_mod=1) == 56

    def test_primal_divine_l20_con1(self):
        assert calculate_hp(level=20, base_hp=10, growth=4, con_mod=1) == 106

    def test_arcane_shadow_l1_con1(self):
        assert calculate_hp(level=1, base_hp=8, growth=3, con_mod=1) == 9

    def test_arcane_shadow_l10_con1(self):
        assert calculate_hp(level=10, base_hp=8, growth=3, con_mod=1) == 45

    def test_arcane_shadow_l20_con1(self):
        assert calculate_hp(level=20, base_hp=8, growth=3, con_mod=1) == 85

    # --- CON +0 ---

    def test_martial_l1_con0(self):
        assert calculate_hp(level=1, base_hp=12, growth=5, con_mod=0) == 12

    def test_martial_l10_con0(self):
        assert calculate_hp(level=10, base_hp=12, growth=5, con_mod=0) == 57

    def test_martial_l20_con0(self):
        assert calculate_hp(level=20, base_hp=12, growth=5, con_mod=0) == 107

    def test_arcane_l1_con0(self):
        assert calculate_hp(level=1, base_hp=8, growth=3, con_mod=0) == 8

    def test_arcane_l20_con0(self):
        assert calculate_hp(level=20, base_hp=8, growth=3, con_mod=0) == 65

    # --- CON +5 ---

    def test_martial_l1_con5(self):
        assert calculate_hp(level=1, base_hp=12, growth=5, con_mod=5) == 17

    def test_martial_l10_con5(self):
        assert calculate_hp(level=10, base_hp=12, growth=5, con_mod=5) == 89

    def test_martial_l20_con5(self):
        assert calculate_hp(level=20, base_hp=12, growth=5, con_mod=5) == 169

    # --- Edge cases ---

    def test_negative_con_modifier(self):
        # CON -1, martial L1: 12 + (-1) = 11
        assert calculate_hp(level=1, base_hp=12, growth=5, con_mod=-1) == 11

    def test_negative_con_level10(self):
        # CON -1, martial L10: 12 + (-1) + 9*(5 + (-1+1)//2) = 11 + 9*(5 + 0) = 11 + 45 = 56
        assert calculate_hp(level=10, base_hp=12, growth=5, con_mod=-1) == 56

    def test_minimum_hp_floor(self):
        # Extreme negative CON should still yield at least 1
        assert calculate_hp(level=1, base_hp=8, growth=3, con_mod=-20) >= 1

    def test_minimum_hp_floor_high_level(self):
        assert calculate_hp(level=5, base_hp=8, growth=3, con_mod=-20) >= 1


class TestCalculateMaxHP:
    def test_warrior_l1(self):
        assert calculate_max_hp("warrior", level=1, con_mod=1) == 13

    def test_mage_l10(self):
        assert calculate_max_hp("mage", level=10, con_mod=1) == 45

    def test_paladin_l20(self):
        assert calculate_max_hp("paladin", level=20, con_mod=1) == 106

    def test_unknown_archetype(self):
        with pytest.raises(ValueError, match="Unknown archetype"):
            calculate_max_hp("necromancer", level=1, con_mod=0)

    def test_warrior_level_progression_1_to_5(self):
        """E2E: level a warrior from 1-5 with CON+1, verify each level's HP."""
        expected = {
            1: 13,  # 12 + 1
            2: 19,  # 12 + 1 + 1*(5 + 1) = 19
            3: 25,  # 12 + 1 + 2*(5 + 1) = 25
            4: 31,  # 12 + 1 + 3*(5 + 1) = 31
            5: 37,  # 12 + 1 + 4*(5 + 1) = 37
        }
        for level, hp in expected.items():
            assert calculate_max_hp("warrior", level=level, con_mod=1) == hp, f"warrior L{level} CON+1: expected {hp}"
