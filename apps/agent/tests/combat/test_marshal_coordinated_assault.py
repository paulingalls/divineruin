"""Coordinated Assault through registered verbs and reloaded combat."""

from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.test_architect_terrain import set_favor
from acceptance.test_kaelen_iron_resolve_capstone import required_player
from combat.test_marshal_direct_strike import arrange, attack, declare_round, hp, order, pending, round_packets
from combat.test_marshal_orders import COORDINATED, DIRECT
from combat.test_marshal_orders import marshal as marshal
from combat.test_marshal_orders import mock_combat_agent_factory as mock_combat_agent_factory
from test_aelora_gift import _live_party


def coordinate(marshal_id: str, first: str, second: str) -> dict:
    return dict(
        kind="ability", actor_id=marshal_id, action=COORDINATED, targets=[first, second], argument_type="", reshape=[]
    )


def assert_attack(packet: dict, roll: int, damage: int) -> None:
    assert (packet["roll"], packet["hit"], packet["damage"]) == (roll, damage > 0, damage)
    assert packet["coordinated_assault"]["order_id"] == COORDINATED


def assert_pincer(packet: dict, host: str, first: str, second: str, foe: str, *, critical=False) -> dict:
    coordinated = packet["coordinated_assault"]
    assert coordinated["source_id"] == host and coordinated["name"] == "Coordinated Assault"
    pincer = coordinated["pincer"]
    assert pincer["target_id"] == foe
    confirming, deferred = pincer["landings"]
    assert (confirming["ally_id"], deferred["ally_id"]) == (second, first)
    assert (confirming["dice"], deferred["dice"]) == ("2d6" if critical else "1d6", "1d6")
    return {"second": confirming, "first": deferred}


@pytest.mark.parametrize("critical", (False, True))
async def test_same_foe_grants_two_advantages_and_attributes_bonuses(marshal, critical) -> None:
    fight = await arrange(marshal)
    host, second, first = fight.players
    foe = fight.enemies[0]
    second_roll = 20 if critical else 16
    raw = 7 if critical else 3
    base = 8 if critical else 4
    packets = await round_packets(
        fight,
        coordinate(host, second, first),
        attack(first, foe),
        attack(second, foe),
        faces=(2, 16, 2, second_roll),
        damage=(("1d8", 4),) * (3 if critical else 2) + (("2d6" if critical else "1d6", raw), ("1d6", 5)),
    )
    grant = packets[host]["order_rider_grant"]
    assert packets[host]["effect_resolution"] == "engine"
    assert grant["source_id"] == host
    assert [(entry["recipient_id"], entry["target_id"]) for entry in grant["recipients"]] == [
        (second, None),
        (first, None),
    ]
    assert_attack(packets[first], 16, 4)
    assert_attack(packets[second], second_roll, base + raw)
    pincer = assert_pincer(packets[second], host, first, second, foe, critical=critical)
    assert (pincer["second"]["raw_damage"], pincer["first"]["raw_damage"]) == (raw, 5)
    assert (pincer["second"]["landing"]["damage"], pincer["first"]["landing"]["damage"]) == (base + raw, 5)
    assert await hp(fight, foe) == 100 - 4 - base - raw - 5
    assert await pending(fight) == {}
    next_packets = await round_packets(fight, attack(first, foe), faces=(2,))
    assert not next_packets[first]["hit"] and "coordinated_assault" not in next_packets[first]


@pytest.mark.parametrize(("same_foe", "first_roll", "second_roll"), [(False, 16, 16), (True, 3, 16), (True, 16, 3)])
async def test_mismatched_or_missed_attacks_spend_advantage_without_pincer(
    marshal, same_foe, first_roll, second_roll
) -> None:
    fight = await arrange(marshal)
    host, second, first = fight.players
    foe, other = fight.enemies
    second_target = foe if same_foe else other
    first_damage = 4 if first_roll == 16 else 0
    second_damage = 4 if second_roll == 16 else 0
    packets = await round_packets(
        fight,
        coordinate(host, first, second),
        attack(first, foe),
        attack(second, second_target),
        faces=(2, first_roll, 2, second_roll),
        damage=(("1d8", 4),) * ((first_damage + second_damage) // 4),
    )
    assert_attack(packets[first], first_roll, first_damage)
    assert_attack(packets[second], second_roll, second_damage)
    assert all("pincer" not in packets[ally]["coordinated_assault"] for ally in (first, second))
    assert await hp(fight, foe) == 100 - first_damage - (second_damage if same_foe else 0)
    assert await hp(fight, other) == 100 - (0 if same_foe else second_damage)
    assert await pending(fight) == {}
    later = await round_packets(fight, attack(second, foe), faces=(16,), damage=(("1d8", 4),))
    assert later[second]["damage"] == 4 and "coordinated_assault" not in later[second]


async def test_unused_partner_expires_at_following_wrap(marshal) -> None:
    fight = await arrange(marshal)
    host, second, first = fight.players
    foe = fight.enemies[0]
    packets = await round_packets(
        fight, coordinate(host, first, second), attack(first, foe), faces=(2, 16), damage=(("1d8", 4),)
    )
    assert_attack(packets[first], 16, 4)
    [rider] = (await pending(fight))[second]
    assert rider["expires_round"] == 2 and rider["first_hit"]["target_id"] == foe
    await declare_round(fight)
    assert await pending(fight) == {second: [rider]}
    await fight.drain()
    assert (await fight.reload()).round_number == 3 and await pending(fight) == {}
    next_packets = await round_packets(fight, attack(second, foe), faces=(16,), damage=(("1d8", 4),))
    assert next_packets[second]["damage"] == 4 and "coordinated_assault" not in next_packets[second]


async def test_first_hit_drops_foe_and_leaves_partners_advantage(marshal) -> None:
    fight = await arrange(marshal)
    host, second, first = fight.players
    foe, other = fight.enemies
    required_player(await fight.reload(), foe).hp_current = 4
    await fight.persist()
    packets = await round_packets(
        fight, coordinate(host, first, second), attack(first, foe), faces=(2, 16), damage=(("1d8", 4),)
    )
    assert packets[first]["target_fallen"] and await hp(fight, foe) == 0
    [rider] = (await pending(fight))[second]
    assert rider["partner_id"] is None and rider["first_hit"] is None
    packets = await round_packets(fight, attack(second, other), faces=(2, 16), damage=(("1d8", 4),))
    assert_attack(packets[second], 16, 4)
    assert "pincer" not in packets[second]["coordinated_assault"]
    assert await hp(fight, other) == 96 and await pending(fight) == {}


async def test_second_hit_drops_foe_before_deferred_die_is_rolled(marshal) -> None:
    fight = await arrange(marshal)
    host, second, first = fight.players
    foe = fight.enemies[0]
    required_player(await fight.reload(), foe).hp_current = 11
    await fight.persist()
    packets = await round_packets(
        fight,
        coordinate(host, first, second),
        attack(first, foe),
        attack(second, foe),
        faces=(2, 16, 2, 16),
        damage=(("1d8", 4), ("1d8", 4), ("1d6", 3)),
    )
    assert_attack(packets[second], 16, 7)
    pincer = assert_pincer(packets[second], host, first, second, foe)
    assert pincer["second"]["raw_damage"] == 3 and pincer["first"]["skipped"] == "target_fallen"
    assert await hp(fight, foe) == 0 and await pending(fight) == {}


@pytest.mark.parametrize("opening_roll", (None, 16, 3), ids=("unused", "hit", "miss"))
async def test_overlapping_order_replaces_pairing_and_preserves_old_partners_advantage(marshal, opening_roll) -> None:
    fight = await arrange(marshal, extra_ally=True)
    host, second, first, newest = fight.players
    foe = fight.enemies[0]
    initial = coordinate(host, first, second)
    first_damage = (("1d8", 4),) if opening_roll == 16 else ()
    if opening_roll is None:
        await round_packets(fight, initial)
    else:
        await round_packets(fight, initial, attack(second, foe), faces=(2, opening_roll), damage=first_damage)
    old = await pending(fight)
    packets = await round_packets(
        fight,
        coordinate(host, second, newest),
        attack(first, foe),
        attack(second, foe),
        attack(newest, foe),
        faces=(2, 16) * 3,
        damage=(("1d8", 4),) * 3 + (("1d6", 3), ("1d6", 5)),
    )
    replacement = packets[host]["order_rider_grant"]
    assert replacement["recipients"][0]["replaced"] == (old[second][0] if opening_roll is None else None)
    assert replacement["scrubbed"] == ([] if opening_roll == 3 else [{"recipient_id": first, **old[first][0]}])
    assert_attack(packets[first], 16, 4)
    assert "pincer" not in packets[first]["coordinated_assault"]
    assert_attack(packets[second], 16, 4)
    assert "pincer" not in packets[second]["coordinated_assault"]
    assert_pincer(packets[newest], host, second, newest, foe)
    assert await hp(fight, foe) == 80 - 4 * (opening_roll == 16)
    assert await pending(fight) == {}


async def test_deferred_damage_uses_first_ally_delivery_and_coexists_with_direct_strike(marshal) -> None:
    fight = await arrange(marshal)
    host, second, first = fight.players
    foe = fight.enemies[0]
    state = await fight.reload()
    required_player(state, first).action_pool[0]["damage_type"] = "piercing"
    required_player(state, foe).damage_affinities = {"resistant": ["piercing"]}
    await fight.persist()
    await round_packets(fight, coordinate(host, first, second), attack(first, foe), faces=(2, 16), damage=(("1d8", 4),))
    packets = await round_packets(
        fight,
        order(fight, foe),
        attack(second, foe),
        faces=(2, 16),
        damage=(("1d8", 4), ("1d4", 2), ("1d6", 3), ("1d6", 5)),
    )
    pincer = assert_pincer(packets[second], host, first, second, foe)
    assert packets[second]["order_rider"] == {
        "order_id": DIRECT,
        "name": "Direct Strike",
        "dice": "1d4",
        "raw_damage": 2,
    }
    assert (pincer["first"]["landing"]["damage_type"], pincer["first"]["landing"]["damage"]) == ("piercing", 2)
    assert pincer["second"]["landing"]["damage"] == 9 and await hp(fight, foe) == 87


@pytest.fixture
async def fate_pair(marshal):
    fight = await arrange(marshal, earlier=True)
    lifecycle = _live_party(fight.sd, *fight.players)
    try:
        yield fight
    finally:
        await lifecycle.aclose()


@pytest.mark.parametrize(("keep", "original"), (("original", 15), ("reroll", 15), ("reroll", 3)))
async def test_fate_keeps_one_second_hit_and_one_deferred_die_after_reload(fate_pair, keep, original) -> None:
    fight = fate_pair
    host, second, first = fight.players
    foe = fight.enemies[0]
    await round_packets(fight, coordinate(host, first, second), attack(first, foe), faces=(2, 16), damage=(("1d8", 4),))
    await set_favor(fight, "zhael", 40)
    await declare_round(fight, attack(second, foe))
    ability = {"id": "zhael_fates_thread"}
    with (
        patch("check_resolution.dice_roll", side_effect=map(_d20, (2, original, 2, 16))) as d20,
        patch("check_resolution_attack.dice_roll", side_effect=map(_damage_die, (4, 3, 5))) as dice,
        patch("combat_damage_settlement.dice_roll", dice),
    ):
        offer = (await fight.command("resolve_phase", {}))["fate_offer"]
        assert offer["roller_id"] == second and offer["die"] == original and host in offer["eligible_followers"]
        assert d20.call_count == 2 and not dice.called and await hp(fight, foe) == 96
        state = await fight.reload()
        assert state.ally_continuation is not None
        cursor = state.ally_continuation["attack"]
        assert cursor["prepared"]["d20"]["advantage"] is True
        assert cursor["attacker_data"]["coordinated_rider"] == (await pending(fight))[second][0]
        ability["offer_id"] = offer["offer_id"]
        reroll = await fight.command("activate", ability)
        assert reroll["reroll"]["die"] == 16 and d20.call_count == 4 and not dice.called
        assert await hp(fight, foe) == 96
        result = await fight.command("activate", {**ability, "keep": keep})
        packet = next(packet for packet in result["packets"] if packet["actor_id"] == second)
        assert_attack(packet, original if keep == "original" else 16, 7)
        pincer = assert_pincer(packet, host, first, second, foe)
        assert pincer["second"]["raw_damage"] == 3 and pincer["first"]["landing"]["damage"] == 5
        assert await hp(fight, foe) == 84 and await pending(fight) == {}
        await fight.drain()
        assert await hp(fight, foe) == 84
    assert [call.args[0] for call in dice.call_args_list] == ["1d8", "1d6", "1d6"]


async def test_deferred_fortitude_hold_reloads_without_repeating_the_attack(fate_pair) -> None:
    fight = fate_pair
    host, second, first = fight.players
    foe = fight.enemies[0]
    state = await fight.reload()
    target = required_player(state, foe)
    target.hp_current = 18
    required_player(state, second).action_pool[0]["critical_save"] = {
        "applies_condition": "deafened",
        "save": "CON",
        "dc": 15,
    }
    target.unholy_fortitude = {"save": "CON", "dc": 10, "increment": 5, "narration_cue": "It rises."}
    await fight.persist()
    await round_packets(fight, coordinate(host, first, second), attack(first, foe), faces=(2, 16), damage=(("1d8", 4),))
    await set_favor(fight, "zhael", 40)
    await declare_round(fight, attack(second, foe))

    async def keep(offer: dict) -> dict:
        return await fight.command(
            "activate", {"id": "zhael_fates_thread", "offer_id": offer["offer_id"], "keep": "original"}
        )

    with (
        patch("check_resolution.dice_roll", side_effect=map(_d20, (2, 20, 7, 2))) as d20,
        patch("check_resolution_attack.dice_roll", side_effect=map(_damage_die, (4, 4, 3, 5))) as dice,
        patch("combat_damage_settlement.dice_roll", dice),
    ):
        swing = (await fight.command("resolve_phase", {}))["fate_offer"]
        assert swing["roll_kind"] == "attack" and swing["roller_id"] == second
        critical = (await keep(swing))["fate_offer"]
        assert critical["roll_kind"] == "save" and critical["roller_id"] == foe and critical["die"] == 7
        save = (await keep(critical))["fate_offer"]
        assert save["roll_kind"] == "save" and save["roller_id"] == foe and save["die"] == 2
        assert await hp(fight, foe) == 3 and await pending(fight) == {}
        result = await keep(save)
        packet = next(packet for packet in result["packets"] if packet["actor_id"] == second)
        pincer = assert_pincer(packet, host, first, second, foe, critical=True)
        assert pincer["first"]["landing"]["unholy_fortitude"]["success"] is False
        assert packet["critical_save"]["roll"] == 7
        assert packet["target_fallen"] and await hp(fight, foe) == 0
        await fight.drain()
    assert d20.call_count == 4
    assert [call.args[0] for call in dice.call_args_list] == ["1d8", "1d8", "2d6", "1d6"]
