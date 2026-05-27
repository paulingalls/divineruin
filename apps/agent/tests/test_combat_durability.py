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

from unittest.mock import AsyncMock, patch

import pytest

import combat_resolution
import combat_support
import event_types as E
from session_data import SessionData


def _inv_item(item_id, item_type, *, tier="standard", equipped=True, current_hits=None, name=None):
    """Build a get_player_inventory-shaped item dict (catalog fields top-level,
    per-instance state under slot_info)."""
    slot = {"quantity": 1, "equipped": equipped}
    if current_hits is not None:
        slot["current_hits"] = current_hits
    item = {"id": item_id, "type": item_type, "durability_tier": tier, "slot_info": slot}
    if name is not None:
        item["name"] = name
    return item


# --- event constant ----------------------------------------------------------


def test_item_durability_hit_event_constant():
    assert E.ITEM_DURABILITY_HIT == "item_durability_hit"


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


# --- _find_equipped ----------------------------------------------------------


def test_find_equipped_matches_type_and_equipped_flag():
    inv = [
        _inv_item("leather_armor_basic", "armor", equipped=False),  # unequipped
        _inv_item("longsword_guild", "weapon", equipped=True),  # wrong type
        _inv_item("plate_armor", "armor", equipped=True),  # the match
    ]
    found = combat_support._find_equipped(inv, "armor")
    assert found is not None and found["id"] == "plate_armor"


def test_find_equipped_returns_none_when_no_match():
    inv = [_inv_item("longsword_guild", "weapon", equipped=True)]
    assert combat_support._find_equipped(inv, "shield") is None


def test_find_equipped_filters_by_name():
    inv = [
        _inv_item("longsword_guild", "weapon", equipped=True, name="Longsword"),
        _inv_item("dagger_iron", "weapon", equipped=True, name="Dagger"),
    ]
    found = combat_support._find_equipped(inv, "weapon", name="dagger")
    assert found is not None and found["id"] == "dagger_iron"


# --- _accrue_durability ------------------------------------------------------


def _session():
    return SessionData(player_id="p1", location_id="loc1", room=None)


async def test_accrue_persists_decremented_hits():
    mutations = AsyncMock()
    item = _inv_item("plate_armor", "armor", tier="standard", current_hits=10)
    with patch.object(combat_support, "publish_game_event", AsyncMock()):
        result = await combat_support._accrue_durability(
            _session(), "p1", item, 1, is_hollow_zone=False, mutations=mutations
        )
    mutations.update_item_durability.assert_awaited_once_with("p1", "plate_armor", 9)
    assert result == {"broken": False, "penalty": {}, "current_hits": 9}


async def test_accrue_hollow_zone_doubles_loss():
    mutations = AsyncMock()
    item = _inv_item("plate_armor", "armor", tier="standard", current_hits=10)
    with patch.object(combat_support, "publish_game_event", AsyncMock()):
        await combat_support._accrue_durability(_session(), "p1", item, 1, is_hollow_zone=True, mutations=mutations)
    mutations.update_item_durability.assert_awaited_once_with("p1", "plate_armor", 8)


async def test_accrue_lazy_defaults_missing_current_hits_to_full():
    mutations = AsyncMock()
    # standard tier max_hits == 10; no current_hits on the row -> reads as 10.
    item = _inv_item("plate_armor", "armor", tier="standard", current_hits=None)
    with patch.object(combat_support, "publish_game_event", AsyncMock()):
        result = await combat_support._accrue_durability(
            _session(), "p1", item, 1, is_hollow_zone=False, mutations=mutations
        )
    mutations.update_item_durability.assert_awaited_once_with("p1", "plate_armor", 9)
    assert result["current_hits"] == 9


async def test_accrue_breaks_at_zero_with_typed_penalty_and_event():
    mutations = AsyncMock()
    item = _inv_item("longsword_guild", "weapon", tier="fragile", current_hits=1)
    with patch.object(combat_support, "publish_game_event", AsyncMock()) as pub:
        result = await combat_support._accrue_durability(
            _session(), "p1", item, 1, is_hollow_zone=False, mutations=mutations
        )
    assert result == {"broken": True, "penalty": {"attack": -2}, "current_hits": 0}
    # event carries the durability-hit payload
    assert pub.await_args is not None
    assert pub.await_args.args[1] == E.ITEM_DURABILITY_HIT
    payload = pub.await_args.args[2]
    assert payload["item_id"] == "longsword_guild" and payload["broken"] is True


async def test_accrue_already_broken_skips_write_and_event():
    mutations = AsyncMock()
    item = _inv_item("longsword_guild", "weapon", tier="fragile", current_hits=0)
    with patch.object(combat_support, "publish_game_event", AsyncMock()) as pub:
        result = await combat_support._accrue_durability(
            _session(), "p1", item, 1, is_hollow_zone=False, mutations=mutations
        )
    mutations.update_item_durability.assert_not_awaited()
    pub.assert_not_awaited()
    assert result == {"broken": True, "penalty": {"attack": -2}, "current_hits": 0}
