"""Tests for the pure durability rules engine (story-001, M5.4).

durability is a closed-table deterministic mechanic (CLAUDE.md golden rule #3):
the 4 durability tiers, their max-hits, the repair-skill-tier coupling, and the
rarity-keyed repair pricing are code constants, not DB-loaded content (same call
as the workspace-vocab SSOT decision). No IO — every function reads/returns plain
dicts/ints, so these are plain unit tests with no fixtures or pool.

Conflicts resolved by this story (recorded as decisions):
- durability-repair-pricing-axis: repair cost keys on item RARITY, not durability.
- durability-repair-skill-tier: fragile->untrained ... masterwork->master.
- durability-broken-penalties: weapon -2 attack / armor|shield -2 AC / tool unusable.
"""

import pytest

import durability

# --- max_hits / DURABILITY_MAX_HITS (spec Durability Tiers table) -------------


@pytest.mark.parametrize(
    "tier,expected",
    [("fragile", 3), ("standard", 10), ("reinforced", 25), ("masterwork", 50)],
)
def test_max_hits_per_tier(tier, expected):
    assert durability.max_hits(tier) == expected


def test_max_hits_unknown_tier_fails_loud():
    with pytest.raises(ValueError):
        durability.max_hits("indestructible")


# --- apply_durability_damage -------------------------------------------------


def test_apply_damage_decrements_by_exactly_hits():
    item = {"type": "weapon", "durability_tier": "standard", "current_hits": 10}
    out = durability.apply_durability_damage(item, 3, is_hollow_zone=False)
    assert out["current_hits"] == 7


def test_apply_damage_does_not_mutate_input():
    item = {"type": "weapon", "durability_tier": "standard", "current_hits": 10}
    durability.apply_durability_damage(item, 3, is_hollow_zone=False)
    assert item["current_hits"] == 10  # caller's dict untouched


def test_apply_damage_floors_at_zero():
    item = {"type": "armor", "durability_tier": "fragile", "current_hits": 2}
    out = durability.apply_durability_damage(item, 5, is_hollow_zone=False)
    assert out["current_hits"] == 0  # never negative


def test_apply_damage_hollow_zone_doubles_loss():
    item = {"type": "weapon", "durability_tier": "reinforced", "current_hits": 25}
    out = durability.apply_durability_damage(item, 3, is_hollow_zone=True)
    assert out["current_hits"] == 25 - 6  # 2 * 3


def test_apply_damage_zero_hits_is_noop():
    item = {"type": "weapon", "durability_tier": "standard", "current_hits": 10}
    out = durability.apply_durability_damage(item, 0, is_hollow_zone=False)
    assert out["current_hits"] == 10


def test_apply_damage_negative_hits_fails_loud():
    item = {"type": "weapon", "durability_tier": "standard", "current_hits": 10}
    with pytest.raises(ValueError):
        durability.apply_durability_damage(item, -1, is_hollow_zone=False)


def test_apply_damage_unknown_tier_fails_loud():
    item = {"type": "weapon", "durability_tier": "bogus", "current_hits": 10}
    with pytest.raises(ValueError):
        durability.apply_durability_damage(item, 1, is_hollow_zone=False)


# --- check_item_condition (broken-state penalties) ---------------------------


def test_condition_not_broken_above_zero():
    item = {"type": "weapon", "durability_tier": "standard", "current_hits": 1}
    cond = durability.check_item_condition(item)
    assert cond == {"broken": False, "penalty": {}}


def test_condition_broken_weapon_minus_two_attack():
    item = {"type": "weapon", "durability_tier": "standard", "current_hits": 0}
    cond = durability.check_item_condition(item)
    assert cond["broken"] is True
    assert cond["penalty"] == {"attack": -2}


def test_condition_broken_armor_minus_two_ac():
    item = {"type": "armor", "durability_tier": "standard", "current_hits": 0}
    cond = durability.check_item_condition(item)
    assert cond["broken"] is True
    assert cond["penalty"] == {"ac": -2}


def test_condition_broken_shield_minus_two_ac():
    item = {"type": "shield", "durability_tier": "standard", "current_hits": 0}
    cond = durability.check_item_condition(item)
    assert cond["penalty"] == {"ac": -2}


def test_condition_broken_tool_unusable():
    item = {"type": "tool", "durability_tier": "standard", "current_hits": 0}
    cond = durability.check_item_condition(item)
    assert cond["broken"] is True
    assert cond["penalty"] == {"unusable": True}


def test_condition_broken_non_equippable_type_no_penalty():
    # consumables and the like have no broken-state penalty even at 0 hits.
    item = {"type": "consumable", "durability_tier": "fragile", "current_hits": 0}
    cond = durability.check_item_condition(item)
    assert cond == {"broken": True, "penalty": {}}


# --- calculate_repair_cost (rarity axis, spec Repair Pricing table) ----------


@pytest.mark.parametrize(
    "rarity,expected_sp",
    [("common", 2), ("uncommon", 10), ("rare", 50), ("legendary", 200)],
)
def test_repair_cost_per_rarity(rarity, expected_sp):
    assert durability.calculate_repair_cost(rarity) == expected_sp


def test_repair_cost_unknown_rarity_fails_loud():
    with pytest.raises(ValueError):
        durability.calculate_repair_cost("mythic")


# --- repair_skill_tier (durability-tier -> required Crafting skill tier) ------


@pytest.mark.parametrize(
    "tier,skill",
    [
        ("fragile", "untrained"),
        ("standard", "trained"),
        ("reinforced", "expert"),
        ("masterwork", "master"),
    ],
)
def test_repair_skill_tier_coupling(tier, skill):
    assert durability.repair_skill_tier(tier) == skill


def test_repair_skill_tier_unknown_fails_loud():
    with pytest.raises(ValueError):
        durability.repair_skill_tier("legendary")  # rarity, not a durability tier
