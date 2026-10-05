"""Tests for resource pool formulas, archetype chassis resource config, and pool calculations.

PoolFormula/ResourceConfig now live in archetypes.py (the chassis SSOT);
PoolMaximums + calculate_max_pools stay in rules_engine. The per-archetype
resource expectations below are hardcoded from the historically-correct values —
an independent anchor pinning the chassis now that ARCHETYPE_RESOURCE_CONFIG is gone.
calculate_max_pools resolves the chassis via the autouse seed_archetypes fixture.
"""

import pytest

from archetypes import PoolFormula, ResourceConfig, get_archetype_chassis
from rules_engine import PoolMaximums, calculate_max_pools

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

# id -> ResourceConfig, the legacy ARCHETYPE_RESOURCE_CONFIG values.
_SF = lambda b, a, d: PoolFormula(base=b, attribute=a, level_divisor=d)  # noqa: E731
EXPECTED_RESOURCE = {
    "warrior": ResourceConfig("stamina_only", _SF(8, "constitution", 1), None),
    "guardian": ResourceConfig("stamina_only", _SF(8, "constitution", 1), None),
    "skirmisher": ResourceConfig("stamina_only", _SF(8, "dexterity", 1), None),
    "rogue": ResourceConfig("stamina_only", _SF(8, "dexterity", 1), None),
    "spy": ResourceConfig("stamina_only", _SF(8, "charisma", 1), None),
    "mage": ResourceConfig("focus_only", None, _SF(8, "intelligence", 1)),
    "artificer": ResourceConfig("focus_only", None, _SF(8, "intelligence", 1)),
    "seeker": ResourceConfig("focus_only", None, _SF(8, "intelligence", 1)),
    "whisper": ResourceConfig("focus_only", None, _SF(6, "intelligence", 2)),
    "druid": ResourceConfig("focus_primary", _SF(4, "constitution", 0), _SF(8, "wisdom", 1)),
    "cleric": ResourceConfig("focus_primary", _SF(4, "constitution", 0), _SF(8, "wisdom", 1)),
    "beastcaller": ResourceConfig("focus_primary", _SF(4, "constitution", 0), _SF(8, "wisdom", 1)),
    "warden": ResourceConfig("focus_primary", _SF(6, "constitution", 0), _SF(8, "wisdom", 1)),
    "paladin": ResourceConfig("focus_primary", _SF(6, "constitution", 3), _SF(6, "wisdom", 1)),
    "oracle": ResourceConfig("focus_primary", _SF(4, "constitution", 0), _SF(8, "wisdom", 1)),
    "bard": ResourceConfig("split", _SF(5, "constitution", 2), _SF(5, "charisma", 2)),
    "diplomat": ResourceConfig("split", _SF(5, "charisma", 2), _SF(5, "charisma", 2)),
    "marshal": ResourceConfig("split", _SF(6, "strength", 2), _SF(5, "charisma", 2)),
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


class TestArchetypeChassisResource:
    def test_all_18_present(self):
        assert len(EXPECTED_RESOURCE) == 18

    @pytest.mark.parametrize("archetype", list(EXPECTED_RESOURCE.keys()))
    def test_resource_matches_expected(self, archetype: str):
        assert get_archetype_chassis(archetype).resource == EXPECTED_RESOURCE[archetype]

    def test_warrior_stamina_config(self):
        r = get_archetype_chassis("warrior").resource
        assert r.pattern == "stamina_only"
        assert r.stamina_formula == PoolFormula(8, "constitution", 1)
        assert r.focus_formula is None

    def test_mage_focus_config(self):
        r = get_archetype_chassis("mage").resource
        assert r.pattern == "focus_only"
        assert r.stamina_formula is None
        assert r.focus_formula == PoolFormula(8, "intelligence", 1)

    def test_druid_focus_primary_flat_secondary(self):
        r = get_archetype_chassis("druid").resource
        assert r.pattern == "focus_primary"
        assert r.stamina_formula is not None and r.stamina_formula.level_divisor == 0  # flat
        assert r.focus_formula is not None and r.focus_formula.level_divisor == 1

    def test_marshal_mixed_attributes(self):
        r = get_archetype_chassis("marshal").resource
        assert r.pattern == "split"
        assert r.stamina_formula is not None and r.stamina_formula.attribute == "strength"
        assert r.focus_formula is not None and r.focus_formula.attribute == "charisma"


class TestCalculateMaxPoolsStaminaOnly:
    @pytest.mark.parametrize(
        "archetype,level,expected",
        [
            pytest.param(
                "warrior", 1, {"stamina": 10, "focus": None, "pattern": "stamina_only"}, id="test_warrior_level_1"
            ),
            pytest.param("warrior", 10, {"stamina": 19}, id="test_warrior_level_10"),
            pytest.param("warrior", 20, {"stamina": 29}, id="test_warrior_level_20"),
            pytest.param("skirmisher", 1, {"stamina": 10, "focus": None}, id="test_skirmisher_uses_dex"),
            pytest.param("spy", 1, {"stamina": 12, "focus": None}, id="test_spy_uses_cha"),
            pytest.param("guardian", 1, {"stamina": 10, "focus": None}, id="test_guardian_level_1"),
            pytest.param("rogue", 1, {"stamina": 10, "focus": None}, id="test_rogue_uses_dex"),
        ],
    )
    def test_pools(self, archetype, level, expected):
        result = calculate_max_pools(archetype, level, POOL_TEST_MODS)
        for field, value in expected.items():
            actual = getattr(result, field)
            if value is None:
                assert actual is None, field
            else:
                assert actual == value, field


class TestCalculateMaxPoolsFocusOnly:
    @pytest.mark.parametrize(
        "archetype,level,expected",
        [
            pytest.param("mage", 1, {"stamina": None, "focus": 12, "pattern": "focus_only"}, id="test_mage_level_1"),
            pytest.param("mage", 10, {"focus": 21}, id="test_mage_level_10"),
            pytest.param("mage", 20, {"focus": 31}, id="test_mage_level_20"),
            pytest.param("artificer", 1, {"focus": 12, "stamina": None}, id="test_artificer_level_1"),
            pytest.param("seeker", 1, {"focus": 12}, id="test_seeker_level_1"),
            pytest.param(
                "whisper",
                1,
                {"focus": 9, "stamina": None, "pattern": "focus_only"},
                id="test_whisper_reduced_formula_level_1",
            ),
            pytest.param("whisper", 10, {"focus": 14}, id="test_whisper_level_10"),
            pytest.param("whisper", 20, {"focus": 19}, id="test_whisper_level_20"),
        ],
    )
    def test_pools(self, archetype, level, expected):
        result = calculate_max_pools(archetype, level, POOL_TEST_MODS)
        for field, value in expected.items():
            actual = getattr(result, field)
            if value is None:
                assert actual is None, field
            else:
                assert actual == value, field


class TestCalculateMaxPoolsFocusPrimary:
    @pytest.mark.parametrize(
        "archetype,level,expected",
        [
            pytest.param("druid", 1, {"stamina": 5, "focus": 11, "pattern": "focus_primary"}, id="test_druid_level_1"),
            pytest.param("druid", 10, {"stamina": 5, "focus": 20}, id="test_druid_level_10_stamina_stays_flat"),
            pytest.param("cleric", 1, {"stamina": 5, "focus": 11}, id="test_cleric_level_1"),
            pytest.param("beastcaller", 1, {"stamina": 5, "focus": 11}, id="test_beastcaller_level_1"),
            pytest.param("warden", 1, {"stamina": 7, "focus": 11}, id="test_warden_higher_flat_stamina"),
            pytest.param("oracle", 1, {"stamina": 5, "focus": 11}, id="test_oracle_level_1"),
            pytest.param("paladin", 1, {"stamina": 7, "focus": 9}, id="test_paladin_stamina_grows_at_third_rate"),
            pytest.param("paladin", 10, {"stamina": 10, "focus": 18}, id="test_paladin_level_10"),
            pytest.param("paladin", 20, {"stamina": 13, "focus": 28}, id="test_paladin_level_20"),
        ],
    )
    def test_pools(self, archetype, level, expected):
        result = calculate_max_pools(archetype, level, POOL_TEST_MODS)
        for field, value in expected.items():
            actual = getattr(result, field)
            if value is None:
                assert actual is None, field
            else:
                assert actual == value, field


class TestCalculateMaxPoolsSplit:
    @pytest.mark.parametrize(
        "archetype,level,expected",
        [
            pytest.param("bard", 1, {"stamina": 6, "focus": 8, "pattern": "split"}, id="test_bard_level_1"),
            pytest.param("bard", 10, {"stamina": 11, "focus": 13}, id="test_bard_level_10"),
            pytest.param("bard", 20, {"stamina": 16, "focus": 18}, id="test_bard_level_20"),
            pytest.param("diplomat", 1, {"stamina": 8, "focus": 8}, id="test_diplomat_both_use_cha"),
            pytest.param("marshal", 1, {"stamina": 8, "focus": 8}, id="test_marshal_mixed_attributes"),
            pytest.param("marshal", 10, {"stamina": 13, "focus": 13}, id="test_marshal_level_10"),
        ],
    )
    def test_pools(self, archetype, level, expected):
        result = calculate_max_pools(archetype, level, POOL_TEST_MODS)
        for field, value in expected.items():
            actual = getattr(result, field)
            if value is None:
                assert actual is None, field
            else:
                assert actual == value, field


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
    @pytest.mark.parametrize("archetype", list(EXPECTED_RESOURCE.keys()))
    def test_level_1_pools_are_positive(self, archetype: str):
        result = calculate_max_pools(archetype, 1, POOL_TEST_MODS)
        if result.stamina is not None:
            assert result.stamina > 0, f"{archetype} L1 stamina <= 0"
        if result.focus is not None:
            assert result.focus > 0, f"{archetype} L1 focus <= 0"

    @pytest.mark.parametrize("archetype", list(EXPECTED_RESOURCE.keys()))
    def test_level_20_pools_are_positive(self, archetype: str):
        result = calculate_max_pools(archetype, 20, POOL_TEST_MODS)
        if result.stamina is not None:
            assert result.stamina > 0, f"{archetype} L20 stamina <= 0"
        if result.focus is not None:
            assert result.focus > 0, f"{archetype} L20 focus <= 0"

    @pytest.mark.parametrize("archetype", list(EXPECTED_RESOURCE.keys()))
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
