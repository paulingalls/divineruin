"""Tests for HP scaling — archetype-based HP formula."""

import pytest

from hp_scaling import (
    ARCHETYPE_HP_CONFIG,
    HPConfig,
    calculate_hp,
    calculate_max_hp,
)
from rules_engine import ARCHETYPE_RESOURCE_CONFIG


class TestHPConfig:
    def test_frozen_dataclass(self):
        cfg = HPConfig(base=12, growth=5, category="martial")
        with pytest.raises(AttributeError):
            cfg.base = 99  # type: ignore[misc]

    def test_fields(self):
        cfg = HPConfig(base=10, growth=4, category="primal_divine")
        assert cfg.base == 10
        assert cfg.growth == 4
        assert cfg.category == "primal_divine"


class TestArchetypeHPConfig:
    def test_has_18_archetypes(self):
        assert len(ARCHETYPE_HP_CONFIG) == 18

    def test_all_keys_lowercase(self):
        for key in ARCHETYPE_HP_CONFIG:
            assert key == key.lower(), f"{key} is not lowercase"

    def test_martial_archetypes(self):
        for name in ("warrior", "guardian", "skirmisher"):
            cfg = ARCHETYPE_HP_CONFIG[name]
            assert cfg.category == "martial"
            assert cfg.base == 12
            assert cfg.growth == 5

    def test_primal_divine_archetypes(self):
        for name in ("druid", "beastcaller", "warden", "cleric", "paladin", "oracle", "marshal"):
            cfg = ARCHETYPE_HP_CONFIG[name]
            assert cfg.category == "primal_divine"
            assert cfg.base == 10
            assert cfg.growth == 4

    def test_arcane_shadow_archetypes(self):
        for name in ("mage", "artificer", "seeker", "rogue", "spy", "whisper", "bard", "diplomat"):
            cfg = ARCHETYPE_HP_CONFIG[name]
            assert cfg.category == "arcane_shadow"
            assert cfg.base == 8
            assert cfg.growth == 3

    def test_keys_match_resource_config(self):
        assert set(ARCHETYPE_HP_CONFIG.keys()) == set(ARCHETYPE_RESOURCE_CONFIG.keys())


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
