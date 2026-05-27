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


def test_find_equipped_skips_equipped_item_missing_durability_tier():
    # A malformed equipped item with no durability_tier must be skipped (None),
    # not returned to _accrue_durability where it would KeyError mid-turn.
    item = {"id": "broken_data", "type": "armor", "slot_info": {"equipped": True}}
    assert combat_support._find_equipped([item], "armor") is None


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


# --- armor + shield accrual in resolve_enemy_turn ----------------------------

import combat_turn  # noqa: E402
from session_data import CombatParticipant, CombatState  # noqa: E402


def _combat_ctx(corruption_level=0):
    ctx = AsyncMock()
    session = SessionData(player_id="p1", location_id="loc1", room=None)
    session.corruption_level = corruption_level
    session.combat_state = CombatState(
        combat_id="c1",
        participants=[
            CombatParticipant(id="p1", name="Kael", type="player", initiative=15, hp_current=25, hp_max=25, ac=14),
            CombatParticipant(
                id="goblin_1",
                name="Goblin",
                type="enemy",
                initiative=12,
                hp_current=7,
                hp_max=7,
                ac=13,
                action_pool=[{"name": "Scimitar", "damage": "1d6", "damage_type": "slashing", "properties": []}],
            ),
        ],
        initiative_order=["p1", "goblin_1"],
        round_number=1,
        current_turn_index=0,
        location_id="loc1",
    )
    ctx.userdata = session
    return ctx


def _forced_attack(*, hit, critical=False):
    res = AsyncMock()
    res.hit = hit
    res.critical = critical
    res.roll = 15
    res.attack_total = 17
    res.damage = 5
    res.damage_type = "slashing"
    res.target_hp_remaining = 20
    res.narrative_hint = "The blade bites."
    return res


async def _run_enemy_turn(ctx, inventory, *, shield_reaction=None, hit=True):
    mutations = AsyncMock()
    queries = AsyncMock()
    queries.get_player_inventory = AsyncMock(return_value=inventory)
    with (
        patch.object(combat_turn.check_resolution, "resolve_attack", return_value=_forced_attack(hit=hit)),
        patch.object(
            combat_turn,
            "_accrue_durability",
            AsyncMock(return_value={"broken": False, "penalty": {}, "current_hits": 9}),
        ) as accrue,
    ):
        await combat_turn._resolve_enemy_turn_impl(
            ctx,
            enemy_id="goblin_1",
            action_name="Scimitar",
            target_id="p1",
            shield_reaction=shield_reaction,
            mutations=mutations,
            queries=queries,
        )
    return accrue


async def test_enemy_hit_accrues_one_armor_hit():
    ctx = _combat_ctx(corruption_level=0)
    armor = _inv_item("plate_armor", "armor", current_hits=10)
    accrue = await _run_enemy_turn(ctx, [armor])
    accrue.assert_awaited_once()
    assert accrue.await_args is not None
    args, kwargs = accrue.await_args.args, accrue.await_args.kwargs
    assert args[2]["id"] == "plate_armor" and args[3] == 1
    assert kwargs["is_hollow_zone"] is False


async def test_enemy_hit_in_hollow_zone_doubles_via_flag():
    ctx = _combat_ctx(corruption_level=2)
    armor = _inv_item("plate_armor", "armor", current_hits=10)
    accrue = await _run_enemy_turn(ctx, [armor])
    assert accrue.await_args is not None
    assert accrue.await_args.kwargs["is_hollow_zone"] is True


async def test_enemy_miss_accrues_no_durability():
    ctx = _combat_ctx()
    armor = _inv_item("plate_armor", "armor", current_hits=10)
    accrue = await _run_enemy_turn(ctx, [armor], hit=False)
    accrue.assert_not_awaited()


async def test_no_armor_equipped_skips_armor_accrual():
    ctx = _combat_ctx()
    accrue = await _run_enemy_turn(ctx, [])  # empty inventory
    accrue.assert_not_awaited()


async def test_shield_reaction_accrues_shield_hit():
    ctx = _combat_ctx()
    inv = [_inv_item("shield_iron", "shield", current_hits=10)]
    accrue = await _run_enemy_turn(ctx, inv, shield_reaction="Shield Wall")
    # one accrual for the shield (no armor equipped)
    accrue.assert_awaited_once()
    assert accrue.await_args is not None
    assert accrue.await_args.args[2]["id"] == "shield_iron"


async def test_shield_reaction_without_shield_equipped_skips():
    ctx = _combat_ctx()
    inv = [_inv_item("plate_armor", "armor", current_hits=10)]
    accrue = await _run_enemy_turn(ctx, inv, shield_reaction="Shield Wall")
    # armor accrues (1), shield does not — only one call, for the armor
    accrue.assert_awaited_once()
    assert accrue.await_args is not None
    assert accrue.await_args.args[2]["id"] == "plate_armor"


# --- weapon crit-vs-heavy flag in request_attack -----------------------------

import check_tools  # noqa: E402

_PLAYER_WITH_WEAPON = {
    "player_id": "p1",
    "equipment": {"main_hand": {"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}},
}


async def _run_request_attack(*, hit, critical, target_ac):
    ctx = AsyncMock()
    ctx.userdata = SessionData(player_id="p1", location_id="loc1", room=None)
    queries = AsyncMock()
    queries.get_player = AsyncMock(return_value=_PLAYER_WITH_WEAPON)
    queries.get_npc_combat_stats = AsyncMock(return_value={"ac": target_ac, "hp": {"current": 20}})
    mutations = AsyncMock()
    attack = _forced_attack(hit=hit, critical=critical)
    attack.target_ac = target_ac
    attack.attack_modifier = 3
    attack.target_killed = False
    attack.target_hp_remaining = 15
    with (
        patch.object(check_tools.check_resolution, "resolve_attack", return_value=attack),
        patch.object(check_tools, "publish_game_event", AsyncMock()),
    ):
        await check_tools._request_attack_impl(
            ctx, target_id="goblin_1", weapon_or_spell="Longsword", queries=queries, mutations=mutations
        )
    return ctx.userdata


async def test_request_attack_marks_weapon_used_even_on_miss():
    session = await _run_request_attack(hit=False, critical=False, target_ac=13)
    assert session.weapon_used_this_encounter is True
    assert session.weapon_crit_vs_heavy is False


async def test_request_attack_sets_crit_vs_heavy_on_crit_against_heavy_target():
    session = await _run_request_attack(hit=True, critical=True, target_ac=18)
    assert session.weapon_used_this_encounter is True
    assert session.weapon_crit_vs_heavy is True


async def test_request_attack_no_crit_flag_on_normal_hit():
    session = await _run_request_attack(hit=True, critical=False, target_ac=18)
    assert session.weapon_crit_vs_heavy is False


async def test_request_attack_no_crit_flag_on_crit_against_light_target():
    session = await _run_request_attack(hit=True, critical=True, target_ac=13)
    assert session.weapon_crit_vs_heavy is False


# --- weapon per-encounter accrual + flag reset in end_combat -----------------

import combat_end  # noqa: E402


async def _run_end_combat(ctx, inventory, *, outcome="victory"):
    mutations = AsyncMock()
    queries = AsyncMock()
    queries.get_player_inventory = AsyncMock(return_value=inventory)
    with patch.object(
        combat_end,
        "_accrue_durability",
        AsyncMock(return_value={"broken": False, "penalty": {}, "current_hits": 9}),
    ) as accrue:
        await combat_end._end_combat_impl(ctx, outcome, mutations=mutations, queries=queries)
    return accrue


async def test_end_combat_accrues_one_weapon_hit_per_encounter():
    ctx = _combat_ctx(corruption_level=0)
    ctx.userdata.weapon_used_this_encounter = True
    weapon = _inv_item("longsword_guild", "weapon", current_hits=10)
    accrue = await _run_end_combat(ctx, [weapon])
    accrue.assert_awaited_once()
    assert accrue.await_args is not None
    assert accrue.await_args.args[2]["id"] == "longsword_guild" and accrue.await_args.args[3] == 1
    assert accrue.await_args.kwargs["is_hollow_zone"] is False


async def test_end_combat_crit_vs_heavy_accrues_two_weapon_hits():
    ctx = _combat_ctx()
    ctx.userdata.weapon_used_this_encounter = True
    ctx.userdata.weapon_crit_vs_heavy = True
    weapon = _inv_item("longsword_guild", "weapon", current_hits=10)
    accrue = await _run_end_combat(ctx, [weapon])
    assert accrue.await_args is not None
    assert accrue.await_args.args[3] == 2


async def test_end_combat_hollow_zone_doubles_via_flag():
    ctx = _combat_ctx(corruption_level=2)
    ctx.userdata.weapon_used_this_encounter = True
    weapon = _inv_item("longsword_guild", "weapon", current_hits=10)
    accrue = await _run_end_combat(ctx, [weapon])
    assert accrue.await_args is not None
    assert accrue.await_args.kwargs["is_hollow_zone"] is True


async def test_end_combat_no_weapon_used_skips_accrual():
    ctx = _combat_ctx()
    # weapon_used_this_encounter stays False
    accrue = await _run_end_combat(ctx, [_inv_item("longsword_guild", "weapon", current_hits=10)])
    accrue.assert_not_awaited()


async def test_end_combat_resets_weapon_flags():
    ctx = _combat_ctx()
    ctx.userdata.weapon_used_this_encounter = True
    ctx.userdata.weapon_crit_vs_heavy = True
    await _run_end_combat(ctx, [_inv_item("longsword_guild", "weapon", current_hits=10)])
    assert ctx.userdata.weapon_used_this_encounter is False
    assert ctx.userdata.weapon_crit_vs_heavy is False


async def test_end_combat_resets_flags_even_when_no_weapon_equipped():
    ctx = _combat_ctx()
    ctx.userdata.weapon_used_this_encounter = True
    accrue = await _run_end_combat(ctx, [])  # no weapon in inventory
    accrue.assert_not_awaited()
    assert ctx.userdata.weapon_used_this_encounter is False
