"""Tests for combat durability hit emission (story-003, M5.4).

Combat accrues per-equipment-type durability hits and persists them, applying the
story-001 durability engine (apply_durability_damage / check_item_condition). The
rules (docs/game_mechanics/game_mechanics_crafting.md:532-540):
- Weapon: 1 hit per encounter; crit vs a heavily-armored target = 2.
- Armor: 1 hit each time the player takes damage.
- Shield: 1 hit per shield reaction.
- Hollow corruption zones double every hit.
- At 0 hits the item is broken (-2 attack / -2 AC / tool unusable).

Decisions exercised here:
- durability-hollow-zone-threshold: is_hollow_zone = corruption_level >= 2.
- durability-heavy-armor-proxy: is_heavily_armored = target_ac >= 17 (enemy stats
  carry only scalar ac).
- durability-current-hits-lazy-default: a missing current_hits reads as full
  (max_hits(tier)); never-damaged items start undamaged.

This module's pure helpers (combat_resolution) are fixture-free unit tests; the
async accrual/wiring tests inject AsyncMock mutations/queries (test_combat_tools style).
"""

import pytest

import combat_resolution

# --- pure helpers: weapon_hits_for_encounter --------------------------------


@pytest.mark.parametrize("crit_vs_heavy,expected", [(False, 1), (True, 2)])
def test_weapon_hits_for_encounter(crit_vs_heavy, expected):
    assert combat_resolution.weapon_hits_for_encounter(crit_vs_heavy) == expected


# --- pure helpers: is_heavily_armored (AC>=17 proxy) ------------------------


@pytest.mark.parametrize(
    "target_ac,expected",
    [(10, False), (16, False), (17, True), (20, True)],
)
def test_is_heavily_armored_threshold(target_ac, expected):
    assert combat_resolution.is_heavily_armored(target_ac) is expected


# --- pure helpers: is_hollow_zone (corruption_level>=2 proxy) ----------------


@pytest.mark.parametrize(
    "corruption_level,expected",
    [(0, False), (1, False), (2, True), (3, True)],
)
def test_is_hollow_zone_threshold(corruption_level, expected):
    assert combat_resolution.is_hollow_zone(corruption_level) is expected
