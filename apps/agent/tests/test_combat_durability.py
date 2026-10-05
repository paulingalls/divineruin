"""Enemy stats have only scalar AC, so heavy armor uses an AC proxy."""

from unittest.mock import AsyncMock, patch

import pytest
from _combat_end_fixtures import (  # noqa: F401  (autouse fixtures)
    default_condition_persistence,
    default_player_row,
)
from inventory_snapshot_fixture import snapshot_query

import combat_durability
import combat_events
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


def test_item_durability_hit_event_constant():
    assert E.ITEM_DURABILITY_HIT == "item_durability_hit"


@pytest.mark.parametrize("crit_vs_heavy,expected", [(False, 1), (True, 2)])
def test_weapon_hits_for_encounter(crit_vs_heavy, expected):
    assert combat_resolution.weapon_hits_for_encounter(crit_vs_heavy) == expected


@pytest.mark.parametrize(
    "target_ac,expected",
    [(10, False), (16, False), (17, True), (20, True)],
)
def test_is_heavily_armored_threshold(target_ac, expected):
    assert combat_resolution.is_heavily_armored(target_ac) is expected


@pytest.mark.parametrize(
    "corruption_level,expected",
    [(0, False), (1, False), (2, True), (3, True)],
)
def test_is_hollow_zone_threshold(corruption_level, expected):
    assert combat_resolution.is_hollow_zone(corruption_level) is expected


def test_find_equipped_matches_type_and_equipped_flag():
    inv = [
        _inv_item("leather_armor_basic", "armor", equipped=False),  # unequipped
        _inv_item("longsword_guild", "weapon", equipped=True),  # wrong type
        _inv_item("plate_armor", "armor", equipped=True),  # the match
    ]
    found = combat_durability._find_equipped(inv, "armor")
    assert found is not None and found["id"] == "plate_armor"


@pytest.mark.parametrize("gear_type", ["weapon", "armor", "shield"])
def test_find_equipped_ignores_equipped_material(gear_type):
    material = _inv_item("wolf_pelt", "material", equipped=True)
    gear = _inv_item("real_gear", gear_type, equipped=True)
    assert combat_durability._find_equipped([material, gear], gear_type) is gear
    assert combat_durability._find_equipped([material], gear_type) is None


def test_find_equipped_returns_none_when_no_match():
    inv = [_inv_item("longsword_guild", "weapon", equipped=True)]
    assert combat_durability._find_equipped(inv, "shield") is None


def test_find_equipped_skips_equipped_item_missing_durability_tier():
    item = {"id": "broken_data", "type": "armor", "slot_info": {"equipped": True}}
    assert combat_durability._find_equipped([item], "armor") is None


def test_find_equipped_filters_by_name():
    inv = [
        _inv_item("longsword_guild", "weapon", equipped=True, name="Longsword"),
        _inv_item("dagger_iron", "weapon", equipped=True, name="Dagger"),
    ]
    found = combat_durability._find_equipped(inv, "weapon", name="dagger")
    assert found is not None and found["id"] == "dagger_iron"


def _session():
    return SessionData(player_id="p1", location_id="loc1", room=None)


async def test_accrue_persists_decremented_hits():
    mutations = AsyncMock()
    item = _inv_item("plate_armor", "armor", tier="standard", current_hits=10)
    with patch.object(combat_events, "publish_game_event", AsyncMock()):
        result = await combat_durability._accrue_durability(
            _session(), "p1", item, 1, is_hollow_zone=False, mutations=mutations
        )
    mutations.update_item_durability.assert_awaited_once_with("p1", "plate_armor", 9, conn=None)
    assert result == {"broken": False, "penalty": {}, "current_hits": 9}


async def test_accrue_hollow_zone_doubles_loss():
    mutations = AsyncMock()
    item = _inv_item("plate_armor", "armor", tier="standard", current_hits=10)
    with patch.object(combat_events, "publish_game_event", AsyncMock()):
        await combat_durability._accrue_durability(_session(), "p1", item, 1, is_hollow_zone=True, mutations=mutations)
    mutations.update_item_durability.assert_awaited_once_with("p1", "plate_armor", 8, conn=None)


async def test_accrue_lazy_defaults_missing_current_hits_to_full():
    mutations = AsyncMock()
    item = _inv_item("plate_armor", "armor", tier="standard", current_hits=None)
    with patch.object(combat_events, "publish_game_event", AsyncMock()):
        result = await combat_durability._accrue_durability(
            _session(), "p1", item, 1, is_hollow_zone=False, mutations=mutations
        )
    mutations.update_item_durability.assert_awaited_once_with("p1", "plate_armor", 9, conn=None)
    assert result["current_hits"] == 9


async def test_accrue_breaks_at_zero_with_typed_penalty_and_event():
    mutations = AsyncMock()
    item = _inv_item("longsword_guild", "weapon", tier="fragile", current_hits=1)
    with patch.object(combat_events, "publish_game_event", AsyncMock()) as pub:
        result = await combat_durability._accrue_durability(
            _session(), "p1", item, 1, is_hollow_zone=False, mutations=mutations
        )
    assert result == {"broken": True, "penalty": {"attack": -2}, "current_hits": 0}
    assert pub.await_args is not None
    assert pub.await_args.args[1] == E.ITEM_DURABILITY_HIT
    payload = pub.await_args.args[2]
    assert payload["item_id"] == "longsword_guild" and payload["broken"] is True


async def test_accrue_already_broken_skips_write_and_event():
    mutations = AsyncMock()
    item = _inv_item("longsword_guild", "weapon", tier="fragile", current_hits=0)
    with patch.object(combat_events, "publish_game_event", AsyncMock()) as pub:
        result = await combat_durability._accrue_durability(
            _session(), "p1", item, 1, is_hollow_zone=False, mutations=mutations
        )
    mutations.update_item_durability.assert_not_awaited()
    pub.assert_not_awaited()
    assert result == {"broken": True, "penalty": {"attack": -2}, "current_hits": 0}


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


def _forced_attack(*, hit, critical=False, damage=None):
    res = AsyncMock()
    res.hit = hit
    res.critical_success = critical
    res.roll = 15
    res.attack_total = 17
    res.damage = (5 if hit else 0) if damage is None else damage
    res.damage_type = "slashing"
    res.target_hp_remaining = 25 - res.damage
    res.narrative_hint = "The blade bites."
    return res


# The one shield-bearing reaction in the catalog, and since story-018 the one thing that reaches
# this parameter on a live path. Named rather than an invented literal ("Shield Wall" was a
# capability nothing produced — constraint 6).
RETALIATING_SHIELD = "guardian_retaliating_shield"


async def _run_enemy_turn(ctx, inventory, *, shield_reaction=None, hit=True, damage=None):
    session = ctx.userdata
    cs = session.combat_state
    attacker = cs.get_participant("goblin_1")
    target = cs.get_participant("p1")
    action = attacker.action_pool[0]
    mutations = AsyncMock()
    queries = AsyncMock()
    queries.get_player_inventory = AsyncMock(return_value=inventory)
    queries.get_inventory_snapshot = snapshot_query(inventory)
    with (
        patch.object(
            combat_support.check_resolution_attack,
            "resolve_attack",
            return_value=_forced_attack(hit=hit, damage=damage),
        ),
        patch.object(
            combat_support,
            "_accrue_durability",
            AsyncMock(return_value={"broken": False, "penalty": {}, "current_hits": 9}),
        ) as accrue,
    ):
        await combat_support._resolve_attack_packet(
            session,
            attacker,
            action,
            target,
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
    accrue = await _run_enemy_turn(ctx, inv, shield_reaction=RETALIATING_SHIELD)
    accrue.assert_awaited_once()
    assert accrue.await_args is not None
    assert accrue.await_args.args[2]["id"] == "shield_iron"


async def test_missed_blow_with_shield_reaction_accrues_shield_hit():
    ctx = _combat_ctx()
    shield = _inv_item("shield_iron", "shield", current_hits=10)
    accrue = await _run_enemy_turn(ctx, [shield], shield_reaction=RETALIATING_SHIELD, hit=False)
    accrue.assert_awaited_once()
    assert accrue.await_args is not None
    assert accrue.await_args.args[2]["id"] == "shield_iron"


# A hit CAN land for 0 damage: check_resolution_attack floors the Minion damage multiplier
# through max(0, int(...)), so "was hit" and "took damage" are separate questions below.
async def test_zero_damage_hit_accrues_no_armor():
    ctx = _combat_ctx()
    armor = _inv_item("plate_armor", "armor", current_hits=10)
    accrue = await _run_enemy_turn(ctx, [armor], hit=True, damage=0)
    accrue.assert_not_awaited()


async def test_zero_damage_hit_with_shield_reaction_wears_only_the_shield():
    ctx = _combat_ctx()
    inv = [_inv_item("plate_armor", "armor", current_hits=10), _inv_item("shield_iron", "shield", current_hits=10)]
    accrue = await _run_enemy_turn(ctx, inv, shield_reaction=RETALIATING_SHIELD, hit=True, damage=0)
    accrue.assert_awaited_once()
    assert accrue.await_args is not None
    assert accrue.await_args.args[2]["id"] == "shield_iron"


async def test_shield_reaction_without_shield_equipped_skips():
    ctx = _combat_ctx()
    inv = [_inv_item("plate_armor", "armor", current_hits=10)]
    accrue = await _run_enemy_turn(ctx, inv, shield_reaction=RETALIATING_SHIELD)
    accrue.assert_awaited_once()
    assert accrue.await_args is not None
    assert accrue.await_args.args[2]["id"] == "plate_armor"


from combat._helpers import _fake_db_mod  # noqa: E402

import combat_end  # noqa: E402


async def _run_end_combat(ctx, inventory, *, outcome="victory"):
    mutations = AsyncMock()
    queries = AsyncMock()
    queries.get_player_inventory = AsyncMock(return_value=inventory)
    queries.get_inventory_snapshot = snapshot_query(inventory)
    with patch.object(
        combat_end,
        "_accrue_durability",
        AsyncMock(return_value={"broken": False, "penalty": {}, "current_hits": 9}),
    ) as accrue:
        await combat_end._end_combat_impl(ctx, outcome, mutations=mutations, queries=queries, db_mod=_fake_db_mod())
    return accrue


async def test_end_combat_accrues_one_weapon_hit_per_encounter():
    ctx = _combat_ctx(corruption_level=0)
    ctx.userdata.party.primary.weapon_used = True
    weapon = _inv_item("longsword_guild", "weapon", current_hits=10)
    accrue = await _run_end_combat(ctx, [weapon])
    accrue.assert_awaited_once()
    assert accrue.await_args is not None
    assert accrue.await_args.args[2]["id"] == "longsword_guild" and accrue.await_args.args[3] == 1
    assert accrue.await_args.kwargs["is_hollow_zone"] is False


async def test_end_combat_crit_vs_heavy_accrues_two_weapon_hits():
    ctx = _combat_ctx()
    ctx.userdata.party.primary.weapon_used = True
    ctx.userdata.party.primary.weapon_crit_vs_heavy = True
    weapon = _inv_item("longsword_guild", "weapon", current_hits=10)
    accrue = await _run_end_combat(ctx, [weapon])
    assert accrue.await_args is not None
    assert accrue.await_args.args[3] == 2


async def test_end_combat_hollow_zone_doubles_via_flag():
    ctx = _combat_ctx(corruption_level=2)
    ctx.userdata.party.primary.weapon_used = True
    weapon = _inv_item("longsword_guild", "weapon", current_hits=10)
    accrue = await _run_end_combat(ctx, [weapon])
    assert accrue.await_args is not None
    assert accrue.await_args.kwargs["is_hollow_zone"] is True


async def test_end_combat_no_weapon_used_skips_accrual():
    ctx = _combat_ctx()
    accrue = await _run_end_combat(ctx, [_inv_item("longsword_guild", "weapon", current_hits=10)])
    accrue.assert_not_awaited()


async def test_end_combat_resets_weapon_flags():
    ctx = _combat_ctx()
    ctx.userdata.party.primary.weapon_used = True
    ctx.userdata.party.primary.weapon_crit_vs_heavy = True
    await _run_end_combat(ctx, [_inv_item("longsword_guild", "weapon", current_hits=10)])
    assert ctx.userdata.party.primary.weapon_used is False
    assert ctx.userdata.party.primary.weapon_crit_vs_heavy is False


async def test_end_combat_resets_flags_even_when_no_weapon_equipped():
    ctx = _combat_ctx()
    ctx.userdata.party.primary.weapon_used = True
    accrue = await _run_end_combat(ctx, [])  # no weapon in inventory
    accrue.assert_not_awaited()
    assert ctx.userdata.party.primary.weapon_used is False


def _add_member(session, player_id: str):
    from caster_state import ConcentrationState, ResonanceTrack
    from party_state import PartyMember
    from session_data import CombatParticipant

    session.party.members.append(
        PartyMember(
            player_id=player_id,
            resonance=ResonanceTrack(),
            concentration=ConcentrationState(),
        )
    )
    # Also register as a combat PARTICIPANT (as combat_init builds it): a member who never entered
    # combat can't have swung, and combat-end durability keys on the participants who fought.
    if session.combat_state is not None:
        session.combat_state.participants.append(
            CombatParticipant(
                id=player_id, name=player_id, type="player", initiative=10, hp_current=20, hp_max=20, ac=14
            )
        )
    return session.party.member(player_id)


async def test_end_combat_accrues_per_member_only_swinging_member():
    ctx = _combat_ctx()
    p2 = _add_member(ctx.userdata, "p2")
    p2.weapon_used = True  # only p2 swung; primary p1 did not
    accrue = await _run_end_combat(ctx, [_inv_item("longsword_guild", "weapon", current_hits=10)])
    accrue.assert_awaited_once()
    assert accrue.await_args is not None
    assert accrue.await_args.args[1] == "p2"  # accrued against p2, not the primary


async def test_end_combat_accrues_each_member_that_swung():
    ctx = _combat_ctx()
    ctx.userdata.party.primary.weapon_used = True
    p2 = _add_member(ctx.userdata, "p2")
    p2.weapon_used = True
    accrue = await _run_end_combat(ctx, [_inv_item("longsword_guild", "weapon", current_hits=10)])
    assert accrue.await_count == 2
    accrued_ids = {call.args[1] for call in accrue.await_args_list}
    assert accrued_ids == {"p1", "p2"}


async def test_end_combat_resets_every_member_weapon_flags():
    ctx = _combat_ctx()
    ctx.userdata.party.primary.weapon_used = True
    p2 = _add_member(ctx.userdata, "p2")
    p2.weapon_used = True
    p2.weapon_crit_vs_heavy = True
    await _run_end_combat(ctx, [_inv_item("longsword_guild", "weapon", current_hits=10)])
    assert p2.weapon_used is False
    assert p2.weapon_crit_vs_heavy is False
