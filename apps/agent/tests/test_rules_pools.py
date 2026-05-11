"""Tests for resource pool formulas, archetype config, and pool calculations."""

import pytest

from rules_engine import (
    ARCHETYPE_RESOURCE_CONFIG,
    PoolFormula,
    PoolMaximums,
    calculate_max_pools,
)

# --- Resource Pools ---

# Standard attribute modifiers for testing:
# STR 14 → +2, DEX 12 → +1, CON 13 → +1, INT 16 → +3, WIS 14 → +2, CHA 16 → +3
POOL_TEST_MODS = {
    "strength": 2,
    "dexterity": 1,
    "constitution": 1,
    "intelligence": 3,
    "wisdom": 2,
    "charisma": 3,
}


class TestPoolFormula:
    def test_construction(self):
        f = PoolFormula(base=8, attribute="constitution", level_divisor=1)
        assert f.base == 8
        assert f.attribute == "constitution"
        assert f.level_divisor == 1

    def test_frozen(self):
        f = PoolFormula(base=8, attribute="constitution", level_divisor=1)
        with pytest.raises(AttributeError):
            f.base = 10  # type: ignore[misc]


class TestPoolMaximums:
    def test_construction_stamina_only(self):
        p = PoolMaximums(stamina=10, focus=None, pattern="stamina_only")
        assert p.stamina == 10
        assert p.focus is None
        assert p.pattern == "stamina_only"

    def test_construction_focus_only(self):
        p = PoolMaximums(stamina=None, focus=12, pattern="focus_only")
        assert p.stamina is None
        assert p.focus == 12

    def test_frozen(self):
        p = PoolMaximums(stamina=10, focus=None, pattern="stamina_only")
        with pytest.raises(AttributeError):
            p.stamina = 5  # type: ignore[misc]


class TestArchetypeResourceConfig:
    def test_has_18_archetypes(self):
        assert len(ARCHETYPE_RESOURCE_CONFIG) == 18

    def test_all_keys_lowercase(self):
        for key in ARCHETYPE_RESOURCE_CONFIG:
            assert key == key.lower(), f"Key {key!r} is not lowercase"

    def test_warrior_stamina_config(self):
        pattern, stamina, focus = ARCHETYPE_RESOURCE_CONFIG["warrior"]
        assert pattern == "stamina_only"
        assert stamina is not None
        assert stamina.base == 8
        assert stamina.attribute == "constitution"
        assert stamina.level_divisor == 1
        assert focus is None

    def test_mage_focus_config(self):
        pattern, stamina, focus = ARCHETYPE_RESOURCE_CONFIG["mage"]
        assert pattern == "focus_only"
        assert stamina is None
        assert focus is not None
        assert focus.base == 8
        assert focus.attribute == "intelligence"
        assert focus.level_divisor == 1

    def test_druid_focus_primary_config(self):
        pattern, stamina, focus = ARCHETYPE_RESOURCE_CONFIG["druid"]
        assert pattern == "focus_primary"
        assert stamina is not None
        assert stamina.level_divisor == 0  # flat
        assert focus is not None
        assert focus.level_divisor == 1  # grows with level

    def test_bard_split_config(self):
        pattern, stamina, focus = ARCHETYPE_RESOURCE_CONFIG["bard"]
        assert pattern == "split"
        assert stamina is not None
        assert focus is not None

    def test_marshal_present(self):
        assert "marshal" in ARCHETYPE_RESOURCE_CONFIG
        pattern, stamina, focus = ARCHETYPE_RESOURCE_CONFIG["marshal"]
        assert pattern == "split"
        assert stamina is not None
        assert stamina.attribute == "strength"
        assert focus is not None
        assert focus.attribute == "charisma"

    def test_whisper_is_focus_only(self):
        pattern, stamina, focus = ARCHETYPE_RESOURCE_CONFIG["whisper"]
        assert pattern == "focus_only"
        assert stamina is None
        assert focus is not None
        assert focus.base == 6
        assert focus.level_divisor == 2


class TestCalculateMaxPoolsStaminaOnly:
    def test_warrior_level_1(self):
        result = calculate_max_pools("warrior", 1, POOL_TEST_MODS)
        # 8 + CON(1) + 1 = 10
        assert result.stamina == 10
        assert result.focus is None
        assert result.pattern == "stamina_only"

    def test_warrior_level_10(self):
        result = calculate_max_pools("warrior", 10, POOL_TEST_MODS)
        # 8 + CON(1) + 10 = 19
        assert result.stamina == 19

    def test_warrior_level_20(self):
        result = calculate_max_pools("warrior", 20, POOL_TEST_MODS)
        # 8 + CON(1) + 20 = 29
        assert result.stamina == 29

    def test_skirmisher_uses_dex(self):
        result = calculate_max_pools("skirmisher", 1, POOL_TEST_MODS)
        # 8 + DEX(1) + 1 = 10
        assert result.stamina == 10
        assert result.focus is None

    def test_spy_uses_cha(self):
        result = calculate_max_pools("spy", 1, POOL_TEST_MODS)
        # 8 + CHA(3) + 1 = 12
        assert result.stamina == 12
        assert result.focus is None

    def test_guardian_level_1(self):
        result = calculate_max_pools("guardian", 1, POOL_TEST_MODS)
        # 8 + CON(1) + 1 = 10
        assert result.stamina == 10
        assert result.focus is None

    def test_rogue_uses_dex(self):
        result = calculate_max_pools("rogue", 1, POOL_TEST_MODS)
        # 8 + DEX(1) + 1 = 10
        assert result.stamina == 10
        assert result.focus is None


class TestCalculateMaxPoolsFocusOnly:
    def test_mage_level_1(self):
        result = calculate_max_pools("mage", 1, POOL_TEST_MODS)
        # 8 + INT(3) + 1 = 12
        assert result.stamina is None
        assert result.focus == 12
        assert result.pattern == "focus_only"

    def test_mage_level_10(self):
        result = calculate_max_pools("mage", 10, POOL_TEST_MODS)
        # 8 + INT(3) + 10 = 21
        assert result.focus == 21

    def test_mage_level_20(self):
        result = calculate_max_pools("mage", 20, POOL_TEST_MODS)
        # 8 + INT(3) + 20 = 31
        assert result.focus == 31

    def test_artificer_level_1(self):
        result = calculate_max_pools("artificer", 1, POOL_TEST_MODS)
        # 8 + INT(3) + 1 = 12
        assert result.focus == 12
        assert result.stamina is None

    def test_seeker_level_1(self):
        result = calculate_max_pools("seeker", 1, POOL_TEST_MODS)
        # 8 + INT(3) + 1 = 12
        assert result.focus == 12

    def test_whisper_reduced_formula_level_1(self):
        result = calculate_max_pools("whisper", 1, POOL_TEST_MODS)
        # 6 + INT(3) + 1//2 = 6 + 3 + 0 = 9
        assert result.focus == 9
        assert result.stamina is None
        assert result.pattern == "focus_only"

    def test_whisper_level_10(self):
        result = calculate_max_pools("whisper", 10, POOL_TEST_MODS)
        # 6 + INT(3) + 10//2 = 6 + 3 + 5 = 14
        assert result.focus == 14

    def test_whisper_level_20(self):
        result = calculate_max_pools("whisper", 20, POOL_TEST_MODS)
        # 6 + INT(3) + 20//2 = 6 + 3 + 10 = 19
        assert result.focus == 19


class TestCalculateMaxPoolsFocusPrimary:
    def test_druid_level_1(self):
        result = calculate_max_pools("druid", 1, POOL_TEST_MODS)
        # Stamina: 4 + CON(1) = 5 (flat)
        # Focus: 8 + WIS(2) + 1 = 11
        assert result.stamina == 5
        assert result.focus == 11
        assert result.pattern == "focus_primary"

    def test_druid_level_10_stamina_stays_flat(self):
        result = calculate_max_pools("druid", 10, POOL_TEST_MODS)
        # Stamina: 4 + CON(1) = 5 (flat — no level scaling)
        assert result.stamina == 5
        # Focus: 8 + WIS(2) + 10 = 20
        assert result.focus == 20

    def test_cleric_level_1(self):
        result = calculate_max_pools("cleric", 1, POOL_TEST_MODS)
        assert result.stamina == 5
        assert result.focus == 11

    def test_beastcaller_level_1(self):
        result = calculate_max_pools("beastcaller", 1, POOL_TEST_MODS)
        assert result.stamina == 5
        assert result.focus == 11

    def test_warden_higher_flat_stamina(self):
        result = calculate_max_pools("warden", 1, POOL_TEST_MODS)
        # Stamina: 6 + CON(1) = 7 (higher base than other focus-primary)
        assert result.stamina == 7
        assert result.focus == 11

    def test_oracle_level_1(self):
        result = calculate_max_pools("oracle", 1, POOL_TEST_MODS)
        assert result.stamina == 5
        assert result.focus == 11

    def test_paladin_stamina_grows_at_third_rate(self):
        result = calculate_max_pools("paladin", 1, POOL_TEST_MODS)
        # Stamina: 6 + CON(1) + 1//3 = 6 + 1 + 0 = 7
        # Focus: 6 + WIS(2) + 1 = 9
        assert result.stamina == 7
        assert result.focus == 9

    def test_paladin_level_10(self):
        result = calculate_max_pools("paladin", 10, POOL_TEST_MODS)
        # Stamina: 6 + CON(1) + 10//3 = 6 + 1 + 3 = 10
        # Focus: 6 + WIS(2) + 10 = 18
        assert result.stamina == 10
        assert result.focus == 18

    def test_paladin_level_20(self):
        result = calculate_max_pools("paladin", 20, POOL_TEST_MODS)
        # Stamina: 6 + CON(1) + 20//3 = 6 + 1 + 6 = 13
        # Focus: 6 + WIS(2) + 20 = 28
        assert result.stamina == 13
        assert result.focus == 28


class TestCalculateMaxPoolsSplit:
    def test_bard_level_1(self):
        result = calculate_max_pools("bard", 1, POOL_TEST_MODS)
        # Stamina: 5 + CON(1) + 1//2 = 5 + 1 + 0 = 6
        # Focus: 5 + CHA(3) + 1//2 = 5 + 3 + 0 = 8
        assert result.stamina == 6
        assert result.focus == 8
        assert result.pattern == "split"

    def test_bard_level_10(self):
        result = calculate_max_pools("bard", 10, POOL_TEST_MODS)
        # Stamina: 5 + CON(1) + 10//2 = 5 + 1 + 5 = 11
        # Focus: 5 + CHA(3) + 10//2 = 5 + 3 + 5 = 13
        assert result.stamina == 11
        assert result.focus == 13

    def test_bard_level_20(self):
        result = calculate_max_pools("bard", 20, POOL_TEST_MODS)
        # Stamina: 5 + CON(1) + 20//2 = 5 + 1 + 10 = 16
        # Focus: 5 + CHA(3) + 20//2 = 5 + 3 + 10 = 18
        assert result.stamina == 16
        assert result.focus == 18

    def test_diplomat_both_use_cha(self):
        result = calculate_max_pools("diplomat", 1, POOL_TEST_MODS)
        # Stamina: 5 + CHA(3) + 1//2 = 5 + 3 + 0 = 8
        # Focus: 5 + CHA(3) + 1//2 = 5 + 3 + 0 = 8
        assert result.stamina == 8
        assert result.focus == 8

    def test_marshal_mixed_attributes(self):
        result = calculate_max_pools("marshal", 1, POOL_TEST_MODS)
        # Stamina: 6 + STR(2) + 1//2 = 6 + 2 + 0 = 8
        # Focus: 5 + CHA(3) + 1//2 = 5 + 3 + 0 = 8
        assert result.stamina == 8
        assert result.focus == 8

    def test_marshal_level_10(self):
        result = calculate_max_pools("marshal", 10, POOL_TEST_MODS)
        # Stamina: 6 + STR(2) + 10//2 = 6 + 2 + 5 = 13
        # Focus: 5 + CHA(3) + 10//2 = 5 + 3 + 5 = 13
        assert result.stamina == 13
        assert result.focus == 13


class TestCalculateMaxPoolsEdgeCases:
    def test_unknown_archetype_raises(self):
        with pytest.raises(ValueError, match="Unknown archetype"):
            calculate_max_pools("barbarian", 1, POOL_TEST_MODS)

    def test_negative_modifier(self):
        low_mods = {
            "strength": -2,
            "dexterity": -1,
            "constitution": -3,
            "intelligence": -1,
            "wisdom": 0,
            "charisma": -2,
        }
        result = calculate_max_pools("warrior", 1, low_mods)
        # 8 + CON(-3) + 1 = 6
        assert result.stamina == 6

    def test_missing_attribute_defaults_to_zero(self):
        sparse_mods: dict[str, int] = {}
        result = calculate_max_pools("warrior", 1, sparse_mods)
        # 8 + 0 + 1 = 9
        assert result.stamina == 9


class TestCalculateMaxPoolsAllArchetypesL1L20:
    """Parametrized sanity check: every archetype produces valid pools at L1 and L20."""

    @pytest.mark.parametrize("archetype", list(ARCHETYPE_RESOURCE_CONFIG.keys()))
    def test_level_1_pools_are_positive(self, archetype: str):
        result = calculate_max_pools(archetype, 1, POOL_TEST_MODS)
        if result.stamina is not None:
            assert result.stamina > 0, f"{archetype} L1 stamina <= 0"
        if result.focus is not None:
            assert result.focus > 0, f"{archetype} L1 focus <= 0"

    @pytest.mark.parametrize("archetype", list(ARCHETYPE_RESOURCE_CONFIG.keys()))
    def test_level_20_pools_are_positive(self, archetype: str):
        result = calculate_max_pools(archetype, 20, POOL_TEST_MODS)
        if result.stamina is not None:
            assert result.stamina > 0, f"{archetype} L20 stamina <= 0"
        if result.focus is not None:
            assert result.focus > 0, f"{archetype} L20 focus <= 0"

    @pytest.mark.parametrize("archetype", list(ARCHETYPE_RESOURCE_CONFIG.keys()))
    def test_level_20_pools_ge_level_1(self, archetype: str):
        l1 = calculate_max_pools(archetype, 1, POOL_TEST_MODS)
        l20 = calculate_max_pools(archetype, 20, POOL_TEST_MODS)
        if l1.stamina is not None:
            assert l20.stamina is not None
            assert l20.stamina >= l1.stamina, f"{archetype} L20 stamina < L1"
        if l1.focus is not None:
            assert l20.focus is not None
            assert l20.focus >= l1.focus, f"{archetype} L20 focus < L1"


class TestCalculateMaxPoolsE2E:
    """E2E acceptance criteria: Warrior vs Mage pools differ correctly."""

    def test_warrior_vs_mage_level_1(self):
        warrior = calculate_max_pools("warrior", 1, POOL_TEST_MODS)
        mage = calculate_max_pools("mage", 1, POOL_TEST_MODS)

        # Warrior: stamina-only, Mage: focus-only
        assert warrior.stamina is not None and warrior.focus is None
        assert mage.stamina is None and mage.focus is not None

        # Warrior stamina = 10, Mage focus = 12
        assert warrior.stamina == 10
        assert mage.focus == 12

    def test_warrior_vs_mage_level_10(self):
        warrior = calculate_max_pools("warrior", 10, POOL_TEST_MODS)
        mage = calculate_max_pools("mage", 10, POOL_TEST_MODS)

        # Both scale linearly: warrior stamina = 19, mage focus = 21
        assert warrior.stamina == 19
        assert mage.focus == 21

        # Pools still exclusive
        assert warrior.focus is None
        assert mage.stamina is None
