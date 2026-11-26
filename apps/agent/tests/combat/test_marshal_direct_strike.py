"""Direct Strike through registered declarations, resolution and combat persistence."""

import json
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_terrain import set_favor
from acceptance.test_kaelen_iron_resolve_capstone import required_player
from combat.test_marshal_orders import DIRECT, enter
from combat.test_marshal_orders import marshal as marshal
from combat.test_marshal_orders import mock_combat_agent_factory as mock_combat_agent_factory
from test_aelora_gift import _live_party

import architect_scene
import db_mutations
import db_queries

HP = 100


async def arrange(
    marshal, *, earlier=False, bonus=False, fate=False, architect=False, extra_ally=False, level=2, owned=()
) -> MawlingHarness:
    location = {"location": "ashmark_architect_works"} if architect else {}
    fight = await marshal(level, extra_ally=extra_ally, owned=owned, **location)
    host, ally, *_ = fight.players
    if bonus:
        player = await db_queries.get_player(ally)
        assert player is not None
        player["equipment"]["main_hand"]["bonus_damage"] = {"dice": "1d6", "damage_type": "fire"}
        await fight.pool.execute("UPDATE players SET data=$2::jsonb WHERE player_id=$1", ally, json.dumps(player))
    if fate:
        await set_favor(fight, "zhael", 40)
        await fight.pool.execute(
            """UPDATE players SET data=data || '{"patron_gifts":{"zhael_lucky":{"spent":true}}}'::jsonb
            WHERE player_id=$1""",
            host,
        )
    if architect:
        fight.encounter_id = "hollow_architect"
    await enter(fight)
    state = await fight.reload()
    assert state.spatial is not None
    initiatives = (25, 30, 20) if earlier else (30, 20, 25)
    for pid, initiative in zip(fight.players, (*initiatives, 15) if extra_ally else initiatives, strict=True):
        actor = required_player(state, pid)
        actor.initiative = initiative
        actor.attributes["strength"] = 10
        state.spatial["positions"][pid] = {"x": 0, "y": 0, "z": 0}
    for pid in fight.enemies:
        foe = required_player(state, pid)
        foe.hp_current = foe.hp_max = HP
        foe.ac = 13
        if bonus:
            foe.damage_affinities = {}
        state.spatial["positions"][pid] = {"x": 5, "y": 0, "z": 0}
    await fight.persist()
    return fight


def order(fight: MawlingHarness, foe: str) -> dict:
    host, ally, _ = fight.players
    return dict(kind="ability", actor_id=host, action=DIRECT, targets=[ally, foe], argument_type="", reshape=[])


def attack(actor: str, foe: str) -> dict:
    return dict(kind="attack", actor_id=actor, action="Longsword", target_id=foe, held_item_id="", rider="", reshape=[])


async def declare_round(fight: MawlingHarness, *actions: dict, error: bool = False) -> dict | str:
    actors = {action["actor_id"] for action in actions}
    state = await fight.reload()
    return await fight.command(
        "declare_phase",
        {
            "declarations": [
                *actions,
                *(
                    dict(kind="defend", actor_id=p.id, reshape=[])
                    for p in state.participants
                    if p.id not in actors and not (p.is_structure or p.is_fallen)
                ),
            ]
        },
        error=error,
    )


async def round_packets(fight: MawlingHarness, *actions: dict, faces=(), damage=()) -> dict:
    await declare_round(fight, *actions)
    with (
        patch("check_resolution.dice_roll", side_effect=map(_d20, faces)) as d20,
        patch("check_resolution_attack.dice_roll", side_effect=[_damage_die(value) for _, value in damage]) as dice,
        patch("combat_damage_settlement.dice_roll", dice),
    ):
        packets = await fight.drain()
    assert [call.args[0] for call in d20.call_args_list] == ["d20"] * len(faces)
    assert [call.args[0] for call in dice.call_args_list] == [notation for notation, _ in damage]
    return {packet["actor_id"]: packet for packet in packets}


async def pending(fight: MawlingHarness) -> dict:
    return (await fight.reload()).order_riders


async def hp(fight: MawlingHarness, foe: str) -> int:
    return required_player(await fight.reload(), foe).hp_current


def assert_strike(packet: dict, *, roll: int = 16, damage: int = 7, dice: str | None = "1d4", raw: int = 3) -> None:
    assert (packet["roll"], packet["hit"], packet["damage"]) == (roll, damage > 0, damage)
    assert packet["order_rider"] == {"order_id": DIRECT, "name": "Direct Strike", "dice": dice, "raw_damage": raw}


def assert_ordinary(packet: dict) -> None:
    assert (packet["roll"], packet["hit"], packet["damage"]) == (2, False, 0)
    assert "order_rider" not in packet


async def test_direct_strike_benefits_only_the_named_ally_once(marshal) -> None:
    fight = await arrange(marshal)
    _, ally, other = fight.players
    foe = fight.enemies[0]
    state = await fight.reload()
    required_player(state, ally).enhancers = ["extra_attack"]
    await fight.persist()
    packets = await round_packets(
        fight,
        order(fight, foe),
        attack(other, foe),
        attack(ally, foe),
        faces=(2, 2, 16, 2),
        damage=(("1d8", 4), ("1d4", 3)),
    )
    assert_ordinary(packets[other])
    first, followup = packets[ally]["attacks"]
    assert_strike(first)
    assert_ordinary(followup)
    assert await hp(fight, foe) == HP - 7
    assert await pending(fight) == {}


async def test_other_foe_does_not_spend_direct_strike(marshal) -> None:
    fight = await arrange(marshal)
    _, ally, _ = fight.players
    foe, other = fight.enemies
    packets = await round_packets(fight, order(fight, foe), attack(ally, other), faces=(16,), damage=(("1d8", 4),))
    packet = packets[ally]
    assert (packet["roll"], packet["hit"], packet["damage"]) == (16, True, 4)
    assert "order_rider" not in packet
    assert (await pending(fight))[ally][0]["target_id"] == foe
    assert await hp(fight, other) == HP - 4
    packets = await round_packets(fight, attack(ally, foe), faces=(2, 16), damage=(("1d8", 4), ("1d4", 3)))
    assert_strike(packets[ally])
    assert await hp(fight, foe) == HP - 7
    assert await pending(fight) == {}


async def test_earlier_ally_uses_direct_strike_next_round(marshal) -> None:
    fight = await arrange(marshal, earlier=True)
    _, ally, _ = fight.players
    foe = fight.enemies[0]
    assert (await fight.reload()).round_checkpoints[0]["combat"]["order_riders"] == {}
    packets = await round_packets(fight, order(fight, foe), attack(ally, foe), faces=(2,))
    assert_ordinary(packets[ally])
    state = await fight.reload()
    grants = await pending(fight)
    assert state.round_number == 2 and grants[ally][0]["expires_round"] == 2
    assert state.round_checkpoints[-1]["combat"]["order_riders"] == grants
    packets = await round_packets(fight, attack(ally, foe), faces=(2, 16), damage=(("1d8", 4), ("1d4", 3)))
    assert_strike(packets[ally])
    assert await hp(fight, foe) == HP - 7
    assert await pending(fight) == {}


async def test_unused_direct_strike_expires_at_following_wrap(marshal) -> None:
    fight = await arrange(marshal)
    _, ally, _ = fight.players
    foe = fight.enemies[0]
    await round_packets(fight, order(fight, foe))
    assert (await pending(fight))[ally][0]["expires_round"] == 2
    await declare_round(fight)
    assert await pending(fight)
    await fight.drain()
    state = await fight.reload()
    assert state.round_number == 3 and await pending(fight) == {}
    assert state.round_checkpoints[-1]["combat"]["order_riders"] == {}
    assert_ordinary((await round_packets(fight, attack(ally, foe), faces=(2,)))[ally])


@pytest.mark.parametrize("architect", (False, True), ids=("ordinary", "retained"))
async def test_unused_direct_strike_dies_with_combat(marshal, architect) -> None:
    fight = await arrange(marshal, architect=architect)
    host, ally, _ = fight.players
    state = await fight.reload()
    foe = fight.enemies[0]
    if architect:
        assert state.architect_encounter is not None
        foe = state.architect_encounter["owner_id"]
    await round_packets(fight, order(fight, foe))
    assert (await pending(fight))[ally][0]["target_id"] == foe
    await fight.command("end_combat", {"outcome": "fled"})
    assert await db_mutations.load_combat_state(state.combat_id) is None
    for pid in fight.players:
        player = await db_queries.get_player(pid)
        assert player is not None
        assert "order_riders" not in player
        assert DIRECT not in json.dumps(player.get("conditions", []))
        if architect and pid == host:
            dormant = json.loads(player["flags"][architect_scene.key(state.location_id)])
            assert dormant["status"] == "dormant"
            assert dormant["snapshot"]["order_riders"] == {}
        else:
            assert DIRECT not in json.dumps(player.get("flags", {}))
    await enter(fight)
    assert (await fight.reload()).combat_id != state.combat_id
    assert await pending(fight) == {}
    assert_ordinary((await round_packets(fight, attack(ally, foe), faces=(2,)))[ally])


@pytest.mark.parametrize("critical", (False, True), ids=("ordinary", "critical"))
async def test_direct_strike_and_weapon_bonus_both_land(marshal, critical) -> None:
    fight = await arrange(marshal, bonus=True)
    _, ally, _ = fight.players
    foe = fight.enemies[0]
    weapon = (("1d8", 4),) * (2 if critical else 1)
    order_die = "2d4" if critical else "1d4"
    raw = 6 if critical else 3
    packets = await round_packets(
        fight,
        order(fight, foe),
        attack(ally, foe),
        faces=(2, 20 if critical else 16),
        damage=(*weapon, ("1d6", 2), (order_die, raw)),
    )
    packet = packets[ally]
    damage = sum(value for _, value in weapon) + 2 + raw
    assert_strike(packet, roll=20 if critical else 16, damage=damage, dice=order_die, raw=raw)
    assert packet["critical"] is critical
    assert (packet["bonus_damage"], packet["bonus_damage_type"], packet["bonus_damage_source"]) == (
        2,
        "fire",
        "Longsword",
    )
    assert await hp(fight, foe) == HP - damage


@pytest.fixture
async def fate_fight(marshal):
    fight = await arrange(marshal, fate=True)
    lifecycle = _live_party(fight.sd, *fight.players)
    try:
        yield fight
    finally:
        await lifecycle.aclose()


@pytest.mark.parametrize("keep", ("original", "reroll"))
async def test_fate_keeps_one_direct_strike_after_reload(fate_fight, keep) -> None:
    fight = fate_fight
    host, ally, _ = fight.players
    foe = fight.enemies[0]
    await declare_round(fight, order(fight, foe), attack(ally, foe))
    ability = {"id": "zhael_fates_thread"}
    with (
        patch("check_resolution.dice_roll", side_effect=map(_d20, (2, 3, 2, 16))) as d20,
        patch("check_resolution_attack.dice_roll", side_effect=map(_damage_die, (4, 3))) as dice,
    ):
        offer = (await fight.command("resolve_phase", {}))["fate_offer"]
        assert offer["roller_id"] == ally and offer["die"] == 3 and host in offer["eligible_followers"]
        assert d20.call_count == 2 and not dice.called and await hp(fight, foe) == HP
        state = await fight.reload()
        grant = (await pending(fight))[ally][0]
        assert state.ally_continuation is not None
        cursor = state.ally_continuation["attack"]
        assert cursor["prepared"]["d20"]["advantage"] is True
        assert cursor["attacker_data"]["order_rider"] == grant
        ability["offer_id"] = offer["offer_id"]
        reroll = await fight.command("activate", ability)
        assert reroll["reroll"]["die"] == 16 and d20.call_count == 4 and not dice.called
        assert (await pending(fight))[ally] == [grant] and await hp(fight, foe) == HP
        result = await fight.command("activate", {**ability, "keep": keep})
    packet = next(packet for packet in result["packets"] if packet["actor_id"] == ally)
    assert packet["resolved"], packet
    if keep == "original":
        assert_strike(packet, roll=3, damage=0, dice=None, raw=0)
        assert not dice.called and await hp(fight, foe) == HP
    else:
        assert_strike(packet)
        assert [call.args[0] for call in dice.call_args_list] == ["1d8", "1d4"]
        assert await hp(fight, foe) == HP - 7
    assert await pending(fight) == {}
    await fight.drain()
    assert_ordinary((await round_packets(fight, attack(ally, foe), faces=(2,)))[ally])


async def test_legacy_row_without_order_riders(marshal) -> None:
    fight = await arrange(marshal)
    _, ally, _ = fight.players
    foe = fight.enemies[0]
    state = await fight.reload()
    row = state.to_dict()
    row.pop("order_riders", None)
    await db_mutations.save_combat_state(state.combat_id, row)
    assert (await fight.reload()).order_riders == {}
    packets = await round_packets(
        fight, order(fight, foe), attack(ally, foe), faces=(2, 16), damage=(("1d8", 4), ("1d4", 3))
    )
    assert_strike(packets[ally])
    assert await pending(fight) == {}


async def test_second_direct_strike_replaces_first(marshal) -> None:
    fight = await arrange(marshal)
    host, ally, _ = fight.players
    first, second = fight.enemies
    await round_packets(fight, order(fight, first))
    old = (await pending(fight))[ally][0]
    packets = await round_packets(fight, order(fight, second), attack(ally, first), faces=(2,))
    assert packets[host]["order_rider_grant"]["replaced"] == old
    assert_ordinary(packets[ally])
    packets = await round_packets(fight, attack(ally, second), faces=(2, 16), damage=(("1d8", 4), ("1d4", 3)))
    assert_strike(packets[ally])
    assert await hp(fight, second) == HP - 7
    assert await pending(fight) == {}
