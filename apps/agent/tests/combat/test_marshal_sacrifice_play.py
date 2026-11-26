"""Sacrifice Play through registered verbs and persisted combat."""

from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_terrain import set_favor
from acceptance.test_kaelen_iron_resolve_capstone import required_player
from combat.test_marshal_direct_strike import attack, declare_round, hp, order, pending, round_packets
from combat.test_marshal_orders import SACRIFICE, enter, pools
from combat.test_marshal_orders import marshal as marshal
from combat.test_marshal_orders import mock_combat_agent_factory as mock_combat_agent_factory
from test_aelora_gift import _live_party

import abilities
import combat_order_riders
import db_mutations_concentration
from combat_damage_affinity import DAMAGE_TYPES
from condition_catalog import IRON_STANCE

NAME = "Sacrifice Play"
HP = 100
PAYMENT = 8
FATE = "zhael_fates_thread"


async def arrange_sacrifice(
    marshal, *, health: int = HP, extra_attack: bool = False, resistant: bool = False
) -> MawlingHarness:
    fight = await marshal(8, stamina=4, owned=(SACRIFICE,))
    await enter(fight)
    host, ally, _ = fight.players
    state = await fight.reload()
    required_player(state, host).initiative = 30
    recipient = required_player(state, ally)
    recipient.hp_current = health
    recipient.attributes["strength"] = 12
    if extra_attack:
        recipient.enhancers = ["extra_attack"]
    if resistant:
        recipient.damage_affinities = {"immune": list(DAMAGE_TYPES), "resistant": [], "vulnerable": []}
        recipient.resist_nonmagical_physical = True
        recipient.conditions = [{"type": IRON_STANCE}]
    assert state.spatial is not None
    for pid in fight.players:
        state.spatial["positions"][pid] = {"x": 0, "y": 0, "z": 0}
    for pid in fight.enemies:
        foe = required_player(state, pid)
        foe.hp_current = foe.hp_max = HP
        foe.ac = 18
        state.spatial["positions"][pid] = {"x": 5, "y": 0, "z": 0}
    await fight.persist()
    return fight


def sacrifice(fight: MawlingHarness, order_id: str = SACRIFICE) -> dict:
    host, ally, _ = fight.players
    return dict(kind="ability", actor_id=host, action=order_id, targets=[ally], argument_type="", reshape=[])


async def assert_ally_hp(fight: MawlingHarness, expected: int) -> None:
    state, (_, ally, _) = await fight.snapshot()
    assert ally is not None
    assert ally["hp"]["current"] == expected
    assert next(p for p in state["participants"] if p["id"] == fight.players[1])["hp_current"] == expected


async def assert_cost_paid(fight: MawlingHarness) -> None:
    host = (await fight.snapshot())[1][0]
    assert host is not None
    assert pools(host) == {"stamina": 0, "focus": 8}


def payment_receipt(packet: dict, ally: str) -> dict:
    assert packet["resolved"] and packet["name"] == NAME and packet["effect_resolution"] == "engine"
    assert packet["deducted"] == {"focus": 0, "stamina": 4}
    payment = packet["payment"]
    assert (payment["dice"], payment["raw_damage"], payment["recipient_id"]) == ("2d6", PAYMENT, ally)
    landing = payment["landing"]
    assert (landing["action"], landing["narrative_hint"], landing["damage_type"], landing["damage"]) == (
        NAME,
        NAME,
        "untyped",
        PAYMENT,
    )
    return landing


def assert_crit(swing: dict, host: str, face: int, damage: int = 10) -> None:
    assert (swing["roll"], swing["hit"], swing["critical"], swing["damage"]) == (face, True, True, damage)
    assert swing["attack_total"] < swing["target_ac"]
    assert (swing["narrative_hint"], swing["context"]) == ("critical success", "critical_hit")
    assert swing["sacrifice_play"] == {"order_id": SACRIFICE, "name": NAME, "source_id": host}


def assert_miss(swing: dict) -> None:
    assert (swing["roll"], swing["hit"], swing["critical"], swing["damage"]) == (2, False, False, 0)
    assert "sacrifice_play" not in swing


@pytest.mark.parametrize(("face", "resistant"), [(2, False), (1, True)])
async def test_payment_and_one_critical_hit(marshal, face, resistant) -> None:
    fight = await arrange_sacrifice(marshal, extra_attack=True, resistant=resistant)
    host, ally, other = fight.players
    foe = fight.enemies[0]
    rows = (await fight.command("query_info", {"kind": "abilities"}))["abilities"]
    order_id = next(row["id"] for row in rows if row["id"] == SACRIFICE and row["combat"])
    _, before = await fight.snapshot()
    await declare_round(fight, sacrifice(fight, order_id), attack(ally, foe))
    assert (await fight.snapshot())[1] == before

    with (
        patch("dice.roll", return_value=_damage_die(PAYMENT)) as payment,
        patch("check_resolution.dice_roll", side_effect=map(_d20, (face, 2))) as d20,
        patch("check_resolution_attack.dice_roll", side_effect=map(_damage_die, (4, 5))) as weapon,
    ):
        packets = (await fight.command("resolve_phase", {}))["packets"]
    assert [p["actor_id"] for p in packets] == [host, ally, other]
    payment.assert_called_once_with("2d6")
    payment_receipt(packets[0], ally)
    authored = abilities.get_ability(order_id)
    assert packets[0]["target_ids"] == [ally]
    assert (packets[0]["effect"], packets[0]["narration_cue"]) == (authored.effect, authored.narration_cue)
    assert "rally_grant" not in packets[0]
    await assert_ally_hp(fight, HP - PAYMENT)
    await assert_cost_paid(fight)
    first, followup = packets[1]["attacks"]
    assert_crit(first, host, face)
    assert_miss(followup)
    assert [call.args[0] for call in d20.call_args_list] == ["d20", "d20"]
    assert [call.args[0] for call in weapon.call_args_list] == ["1d8", "1d8"]
    assert await hp(fight, foe) == HP - 10
    assert await pending(fight) == {}
    assert all(p.get("action") != SACRIFICE for p in await fight.drain())
    await assert_cost_paid(fight)


async def test_fallen_ally_keeps_unused_rider_until_following_wrap(marshal) -> None:
    fight = await arrange_sacrifice(marshal, health=6)
    host, ally, _ = fight.players
    await declare_round(fight, sacrifice(fight), attack(ally, fight.enemies[0]))
    with (
        patch("dice.roll", return_value=_damage_die(PAYMENT)),
        patch("check_resolution.dice_roll", return_value=_d20(12)) as d20,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)) as weapon,
    ):
        packets = (await fight.command("resolve_phase", {}))["packets"]
        landing = payment_receipt(next(p for p in packets if p["actor_id"] == host), ally)
        assert landing["target_fallen"]
        await assert_ally_hp(fight, 0)
        state = await fight.reload()
        assert required_player(state, ally).is_fallen
        assert host not in state.encounter_facts["ally_downers"]
        assert not any(p.get("roll") is not None for p in packets if p["actor_id"] == ally)
        d20.assert_not_called()
        await fight.drain()
        [rider] = (await pending(fight))[ally]
        assert rider["expires_round"] == 2
        await round_packets(fight)
    assert not weapon.called
    assert (await fight.reload()).round_number == 3
    assert await pending(fight) == {}


async def test_hollowed_echo_neither_gains_nor_uses_an_order_rider(marshal) -> None:
    fight = await arrange_sacrifice(marshal, health=6)
    host, ally, other = fight.players
    state = await fight.reload()
    required_player(state, ally).conditions = [{"type": "hollowed", "duration": None, "source": "veil", "stage": 2}]
    combat_order_riders.grant_coordinated_assault(state, host, [ally, other])
    await fight.persist()

    with patch("dice.roll", return_value=_damage_die(PAYMENT)):
        packets = await round_packets(fight, sacrifice(fight))
    assert "order_rider_grant" not in packets[host]
    assert required_player(await fight.reload(), ally).type == "temporary_hollowed"
    assert [r["kind"] for r in (await pending(fight))[ally]] == ["coordinated_assault"]

    await declare_round(fight, attack(ally, host))
    with patch("check_resolution.dice_roll", return_value=_d20(2)) as d20:
        packets = await fight.drain()
    d20.assert_called_once()
    (swing,) = [p for p in packets if p["actor_id"] == ally]
    assert swing["roll"] == 2 and not swing["hit"]
    assert "coordinated_assault" not in swing


async def test_direct_strike_bonus_doubles_with_sacrifice_play(marshal) -> None:
    fight = await arrange_sacrifice(marshal)
    host, ally, _ = fight.players
    foe = fight.enemies[0]
    await round_packets(fight, order(fight, foe))
    with patch("dice.roll", return_value=_damage_die(PAYMENT)):
        packets = await round_packets(
            fight, sacrifice(fight), attack(ally, foe), faces=(2, 2), damage=(("1d8", 4), ("1d8", 5), ("2d4", 6))
        )
    assert_crit(packets[ally], host, 2, damage=16)
    assert packets[ally]["order_rider"] == {
        "order_id": "marshal_direct_strike",
        "name": "Direct Strike",
        "dice": "2d4",
        "raw_damage": 6,
    }
    assert await hp(fight, foe) == HP - 16
    assert await pending(fight) == {}


@pytest.fixture
async def fate_fight(marshal):
    fight = await arrange_sacrifice(marshal, extra_attack=True)
    await set_favor(fight, "zhael", 40)
    await fight.pool.execute(
        """UPDATE players SET data=data || '{"patron_gifts":{"zhael_lucky":{"spent":true}}}'::jsonb
        WHERE player_id=$1""",
        fight.players[0],
    )
    lifecycle = _live_party(fight.sd, *fight.players)
    try:
        yield fight
    finally:
        await lifecycle.aclose()


async def test_payment_settles_once_when_concentration_is_fate_held(fate_fight) -> None:
    fight = fate_fight
    host, ally, _ = fight.players
    spell = "divine_bless"
    await db_mutations_concentration.update_player_concentration(ally, spell)
    fight.sd.member_state(ally).concentration.spell_id = spell
    await declare_round(fight, sacrifice(fight))
    with (
        patch("dice.roll", return_value=_damage_die(PAYMENT)) as payment,
        patch("check_resolution.dice_roll", return_value=_d20(2)) as d20,
    ):
        offer = (await fight.command("resolve_phase", {}))["fate_offer"]
        assert (offer["roll_kind"], offer["roller_id"], offer["die"]) == ("save", ally, 2)
        await assert_ally_hp(fight, HP - PAYMENT)
        state = await fight.reload()
        assert state.ally_continuation["steps"]["sacrifice_payment"]["damage_receipt"]["response"]["damage"] == PAYMENT
        assert not state.order_riders
        result = await fight.command("activate", {"id": FATE, "offer_id": offer["offer_id"], "keep": "original"})
        packet = next(p for p in result["packets"] if p["actor_id"] == host)
        assert payment_receipt(packet, ally)["concentration_broken"] == spell
        assert packet["rally_grant"]["marshal_id"] == host
        [rider] = (await pending(fight))[ally]
        assert rider["order_id"] == SACRIFICE and packet["order_rider_grant"]["replaced"] is None
        assert all(p.get("action") != SACRIFICE for p in await fight.drain())
        await assert_ally_hp(fight, HP - PAYMENT)
        await assert_cost_paid(fight)
        payment.assert_called_once_with("2d6")
        assert d20.call_count == 1


@pytest.mark.parametrize("keep", ["original", "reroll"])
async def test_fate_held_attack_spends_rider_on_one_landing(fate_fight, keep) -> None:
    fight = fate_fight
    host, ally, _ = fight.players
    foe = fight.enemies[0]
    with patch("dice.roll", return_value=_damage_die(PAYMENT)):
        await round_packets(fight, sacrifice(fight))
    [grant] = (await pending(fight)).get(ally, [])
    await declare_round(fight, attack(ally, foe))
    with (
        patch("check_resolution.dice_roll", side_effect=map(_d20, (2, 3, 2))) as d20,
        patch("check_resolution_attack.dice_roll", side_effect=map(_damage_die, (4, 5))) as weapon,
    ):
        offer = (await fight.command("resolve_phase", {}))["fate_offer"]
        assert (offer["roll_kind"], offer["roller_id"], offer["die"]) == ("attack", ally, 2)
        state = await fight.reload()
        assert state.order_riders[ally] == [grant]
        assert state.ally_continuation["attack"]["attacker_data"]["sacrifice_rider"] == grant
        assert not weapon.called and await hp(fight, foe) == HP
        ability = {"id": FATE, "offer_id": offer["offer_id"]}
        assert (await fight.command("activate", ability))["reroll"]["die"] == 3
        assert not weapon.called and (await pending(fight))[ally] == [grant]
        result = await fight.command("activate", {**ability, "keep": keep})
        first, followup = next(p for p in result["packets"] if p["actor_id"] == ally)["attacks"]
        assert_crit(first, host, 3 if keep == "reroll" else 2)
        assert_miss(followup)
        await fight.drain()
    assert d20.call_count == 3
    assert [call.args[0] for call in weapon.call_args_list] == ["1d8", "1d8"]
    assert await pending(fight) == {}
    assert await hp(fight, foe) == HP - 10
