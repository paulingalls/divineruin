"""Tests for the pure gathering resolver (M4.6c / story-001).

Pure functions, no DB/RNG/fixtures — the caller supplies the gathering roll_total,
mirroring test_travel.py / test_social_resolution.py. Spec:
docs/game_mechanics/game_mechanics_combat.md §Gathering During Travel (L977-1060).
"""

import pytest

import gathering

# A representative regional resource table: rarity-keyed material id buckets.
# This dict shape is the interface contract with story-002 (content) / story-003 (tool).
_TABLE = {
    "common": ("medicinal_herbs", "wood"),
    "uncommon": ("iron_ore", "quality_wood"),
    "rare": ("power_crystal",),
}

# --- Skill routing (spec L979-988) ---


def test_metals_stone_gems_route_to_survival():
    for material in ("metals", "stone", "gems"):
        assert gathering.gathering_skill(material) == "survival"


def test_wood_plant_herbs_route_to_nature():
    for material in ("wood", "plant", "herbs"):
        assert gathering.gathering_skill(material) == "nature"


def test_arcane_components_route_to_arcana():
    assert gathering.gathering_skill("arcane_components") == "arcana"


def test_general_foraging_defaults_to_survival():
    assert gathering.gathering_skill(None) == "survival"


def test_unknown_material_type_fails_loud():
    with pytest.raises(ValueError, match="unknown material type"):
        gathering.gathering_skill("antimatter")


# --- Skill-tier access gating (spec L1018-1022) ---


def test_untrained_reaches_only_common():
    assert gathering.accessible_rarities("untrained") == ("common",)


def test_trained_reaches_uncommon():
    assert gathering.accessible_rarities("trained") == ("common", "uncommon")


def test_expert_reaches_rare():
    assert "rare" in gathering.accessible_rarities("expert")


def test_master_reaches_rare():
    assert "rare" in gathering.accessible_rarities("master")


def test_unknown_skill_tier_fails_loud():
    with pytest.raises(ValueError, match="unknown skill tier"):
        gathering.accessible_rarities("legendary")


# --- Result tiers (spec L997-1006) ---


def test_result_tier_thresholds():
    assert gathering.gathering_result_tier(20, 10, master=False) == "rich_find"  # >= dc+10
    assert gathering.gathering_result_tier(10, 10, master=False) == "success"  # >= dc
    assert gathering.gathering_result_tier(6, 10, master=False) == "partial"  # >= dc-5
    assert gathering.gathering_result_tier(4, 10, master=False) == "nothing"  # below


def test_master_rich_find_threshold_reduced_by_five():
    # A roll of dc+5 is only "success" untrained but "rich_find" for a master (spec L1022).
    assert gathering.gathering_result_tier(15, 10, master=False) == "success"
    assert gathering.gathering_result_tier(15, 10, master=True) == "rich_find"


def test_master_never_returns_nothing():
    # "Master: always find something" (spec L1021) — floors to partial.
    assert gathering.gathering_result_tier(1, 10, master=True) == "partial"


# --- Material selection ---


def test_nothing_yields_no_materials():
    mats = gathering.select_materials(_TABLE, "nothing", "expert")
    assert mats == ()


def test_partial_yields_a_common_material():
    mats = gathering.select_materials(_TABLE, "partial", "expert")
    assert mats == ("medicinal_herbs",)  # downgrade to common bucket


def test_success_picks_highest_accessible_bucket():
    untrained = gathering.select_materials(_TABLE, "success", "untrained")
    trained = gathering.select_materials(_TABLE, "success", "trained")
    assert untrained == ("medicinal_herbs",)  # untrained capped at common
    assert trained == ("iron_ore",)  # trained reaches uncommon


def test_rich_find_doubles_quantity():
    mats = gathering.select_materials(_TABLE, "rich_find", "expert")
    assert mats == ("power_crystal", "power_crystal")  # rare bucket, doubled


def test_empty_bucket_falls_back_to_next_lower_accessible():
    table = {"common": ("wood",), "uncommon": (), "rare": ()}
    mats = gathering.select_materials(table, "rich_find", "master")
    assert mats == ("wood", "wood")  # rare+uncommon empty -> common, still doubled


# --- resolve_gathering ---


def test_resolve_returns_result_with_materials_and_dc_margin():
    result = gathering.resolve_gathering(
        material_type="herbs", skill_tier="trained", gathering_dc=10, roll_total=12, resource_table=_TABLE
    )
    assert result.result == "success"
    assert result.dc == 10
    assert result.margin == 2
    assert result.materials == ("iron_ore",)


def test_rich_find_flags_discovery():
    result = gathering.resolve_gathering(
        material_type=None, skill_tier="expert", gathering_dc=10, roll_total=20, resource_table=_TABLE
    )
    assert result.result == "rich_find"
    assert result.discovery is True


def test_non_rich_find_does_not_flag_discovery():
    result = gathering.resolve_gathering(
        material_type=None, skill_tier="expert", gathering_dc=10, roll_total=10, resource_table=_TABLE
    )
    assert result.result == "success"
    assert result.discovery is False


def test_time_cost_per_result_tier():
    def cost(roll, tier="expert"):
        return gathering.resolve_gathering(
            material_type=None, skill_tier=tier, gathering_dc=10, roll_total=roll, resource_table=_TABLE
        ).time_cost

    assert cost(4) == pytest.approx(0.5)  # nothing
    assert cost(6) == pytest.approx(1.0)  # partial
    assert cost(10) == pytest.approx(1.0)  # success
    assert cost(20) == pytest.approx(2.0)  # rich_find


# --- Dramatic verdict (delegated to the M4.5 SSOT) ---


def test_natural_twenty_is_dramatic():
    result = gathering.resolve_gathering(
        material_type=None, skill_tier="trained", gathering_dc=10, roll_total=30, resource_table=_TABLE, raw_die=20
    )
    assert result.dramatic is True
    assert result.context == "natural_20"


def test_natural_one_is_dramatic():
    result = gathering.resolve_gathering(
        material_type=None, skill_tier="trained", gathering_dc=10, roll_total=2, resource_table=_TABLE, raw_die=1
    )
    assert result.dramatic is True
    assert result.context == "natural_1"


def test_razor_thin_margin_is_dramatic():
    result = gathering.resolve_gathering(
        material_type=None, skill_tier="trained", gathering_dc=10, roll_total=10, resource_table=_TABLE, raw_die=8
    )
    assert result.margin == 0
    assert result.dramatic is True
    assert result.context == "razor_thin"


def test_ordinary_clear_pass_is_not_dramatic():
    result = gathering.resolve_gathering(
        material_type=None, skill_tier="trained", gathering_dc=10, roll_total=14, resource_table=_TABLE, raw_die=10
    )
    assert result.dramatic is False
    assert result.context == ""


# --- Determinism + fail-loud ---


def test_same_inputs_yield_identical_result():
    def resolve():
        return gathering.resolve_gathering(
            material_type="metals",
            skill_tier="expert",
            gathering_dc=12,
            roll_total=15,
            resource_table=_TABLE,
            raw_die=9,
        )

    assert resolve() == resolve()


def test_resolve_unknown_material_type_fails_loud():
    with pytest.raises(ValueError, match="unknown material type"):
        gathering.resolve_gathering(
            material_type="dark_matter", skill_tier="expert", gathering_dc=10, roll_total=10, resource_table=_TABLE
        )


def test_resolve_unknown_skill_tier_fails_loud():
    with pytest.raises(ValueError, match="unknown skill tier"):
        gathering.resolve_gathering(
            material_type=None, skill_tier="demigod", gathering_dc=10, roll_total=10, resource_table=_TABLE
        )
