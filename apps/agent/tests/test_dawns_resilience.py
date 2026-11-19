"""Dawn's Resilience through registered spell and item commands."""

import pytest
from _item_heal_fixtures import ItemHealWalk, heal_roll
from _item_heal_fixtures import item_heal_walk as item_heal_walk
from _spell_heal_fixtures import MASS, REGENERATE, WOUNDS
from acceptance.seeds import seed_known_spells
from sample_fixtures import published_payloads
from test_heal_over_time import declare_defend, effects, set_hp
from test_spell_heal_landing import receipt

import spells

GIFT = "orenthel_dawns_resilience"
ORENTHEL = {"patron": "orenthel", "level": 0, "max": 100}


async def prepare_follower(walk, spell, *, hp=10, wisdom=16):
    await walk.prepare(spell, wisdom=wisdom)
    await walk.patch(hp={"current": hp, "max": 20}, divine_favor=ORENTHEL)


def assert_gift(packet, targets, *, healed=2, hp=12):
    gift = packet["gift_triggered"]
    assert set(gift["target_ids"]) == set(targets)
    assert len(gift["target_ids"]) == len(targets)
    assert {k: v for k, v in gift.items() if k != "target_ids"} == {
        "id": GIFT,
        "name": "Dawn's Resilience",
        "healed": healed,
        "hp_current": hp,
        "hp_max": 20,
    }


async def assert_hp(walk, combat, expected):
    saved = await walk.checkpoint() if combat else None
    for pid, hp in expected.items():
        if pid != "companion":
            assert (await walk.read(pid))["hp"]["current"] == hp
        if saved:
            assert saved.get_participant(pid).hp_current == hp


def assert_hp_push(walk, pid, hp):
    calls = walk.sd.room.local_participant.publish_data.call_args_list
    pushes = [
        payload
        for call, payload in zip(calls, published_payloads(walk.sd.room), strict=True)
        if call.kwargs.get("destination_identities") == [pid] and payload["type"] == "hp_changed"
    ]
    assert pushes == [{"type": "hp_changed", "current": hp, "max": 20}]


@pytest.mark.parametrize("combat", [False, True])
async def test_heal_wounds_rewards_only_an_orenthel_healer(walk, combat):
    await ally_heal(walk, combat)
    await walk.patch(divine_favor={"patron": "veythar", "level": 0, "max": 100})
    await walk.patch_row(walk.player, hp={"current": 10, "max": 20})
    ally = await walk.add_player()
    if combat:
        await walk.fight()
    with heal_roll(5):
        packet = await walk.cast(WOUNDS, targets=[ally], combat=combat)
    assert "gift_triggered" not in packet
    await assert_hp(walk, combat, {walk.player: 10, ally: 11})


async def ally_heal(walk, combat, *, start=10, bonus=2):
    await prepare_follower(walk, WOUNDS, hp=start)
    ally = await walk.add_player()
    if combat:
        await walk.fight()
        await walk.declare(WOUNDS, [ally])
    with heal_roll(5):
        if combat:
            first = await walk.command("resolve_phase", {})
            packet = next(p["cast"] for p in first["packets"] if p["actor_id"] == walk.player)
            walk.sd.combat_state = await walk.checkpoint()
            if first["beat"] != "declaration":
                assert not any(p.get("cast") for p in await walk.wrap())
        else:
            packet = await walk.cast(WOUNDS, targets=[ally])
    assert packet["healing_results"] == [receipt(ally, 8, 11)]
    await assert_hp(walk, combat, {walk.player: start + bonus, ally: 11})
    assert_gift(packet, [ally], healed=bonus, hp=start + bonus)
    assert await walk.focus() == 30 - spells.get_spell(WOUNDS).focus_cost
    if not combat:
        assert_hp_push(walk, walk.player, start + bonus)


async def test_non_primary_caster_uses_their_own_patron(walk):
    guest = await walk.add_player(hp=10)
    walk.sd.patron_id = "veythar"
    await walk.patch_row(
        guest, **{"class": "cleric"}, level=20, divine_favor=ORENTHEL, focus={"current": 30, "max": 30}
    )
    await seed_known_spells(walk.pool, guest, (WOUNDS,))
    with heal_roll(5):
        packet = await walk.command("activate", {"id": WOUNDS, "target_id": walk.player}, actor=guest)
    assert_gift(packet, [walk.player])
    await assert_hp(walk, False, {guest: 12})
    assert_hp_push(walk, guest, 12)


@pytest.mark.parametrize("combat", [False, True])
async def test_self_casts_and_zero_recipient_gains_add_no_bonus(walk, combat):
    await ally_heal(walk, combat, start=19, bonus=1)
    full = await walk.add_player(hp=20)
    injured = await walk.add_player()
    for target, wisdom, roll, start, healer_hp, target_gain in [
        (walk.player, 16, 5, 10, 18, 8),
        (full, 16, 5, 10, 10, 0),
        (injured, 2, 1, 10, 10, 0),
        (injured, 16, 5, 20, 20, 8),
    ]:
        await prepare_follower(walk, WOUNDS, hp=start, wisdom=wisdom)
        if combat:
            await walk.fight()
        with heal_roll(roll):
            packet = await walk.cast(WOUNDS, targets=[target], combat=combat)
        assert "gift_triggered" not in packet
        assert packet["healing_results"][0]["healed"] == target_gain
        await assert_hp(walk, combat, {walk.player: healer_hp})
        assert await walk.focus() == 30 - spells.get_spell(WOUNDS).focus_cost


@pytest.mark.parametrize("combat", [False, True])
async def test_mass_heal_adds_two_per_other_creature_actually_healed(walk, combat):
    await prepare_follower(walk, MASS, wisdom=10)
    injured = [await walk.add_player() for _ in range(2)]
    full = await walk.add_player(hp=20)
    if combat:
        injured.append("companion")
        await walk.fight(companion=True)
    else:
        injured.append(await walk.add_player())
    with heal_roll(2):
        packet = await walk.cast(MASS, combat=combat)
    results = {r["target_id"]: r for r in packet["healing_results"]}
    assert results == {
        walk.player: receipt(walk.player, 2, 12, rolled=2, modifier=0),
        full: receipt(full, 0, 20, rolled=2, modifier=0),
        **{pid: receipt(pid, 2, 5, rolled=2, modifier=0) for pid in injured},
    }
    assert_gift(packet, injured, healed=6, hp=18)
    await assert_hp(walk, combat, {walk.player: 18, full: 20, **dict.fromkeys(injured, 5)})
    if not combat:
        assert_hp_push(walk, walk.player, 18)


@pytest.mark.parametrize("combat", [False, True])
async def test_administering_a_potion_credits_the_holder(walk, combat):
    await prepare_follower(walk, WOUNDS)
    ally = await walk.add_player()
    full = await walk.add_player(hp=20)
    await walk.put(quantity=3)
    if combat:
        await walk.fight()
    for remaining, target, target_hp, healer_hp in [(2, ally, 10, 12), (1, full, 20, 12), (0, walk.player, 19, 19)]:
        with heal_roll(7):
            if combat:
                await walk.declare_item(target=target)
                packet = await walk.resolve_item()
                await walk.wrap()
            else:
                packet = await walk.consume(target=target)
        assert packet["remaining_quantity"] == await walk.quantity() == remaining
        await assert_hp(walk, combat, {target: target_hp, walk.player: healer_hp})
        assert await walk.focus() == 30
        if target == ally:
            assert_gift(packet, [ally])
            if not combat:
                assert_hp_push(walk, walk.player, 12)
        else:
            assert "gift_triggered" not in packet


@pytest.mark.parametrize("combat", [False, True])
async def test_regenerate_awards_the_cast_once(walk, combat):
    await prepare_follower(walk, REGENERATE)
    ally = await walk.add_player(hp=10, maximum=40)
    if combat:
        state = await walk.fight()
        state.get_participant(ally).initiative = state.get_participant(walk.player).initiative + 1
    with heal_roll(19):
        packet = await walk.cast(REGENERATE, targets=[ally], combat=combat)
    assert_gift(packet, [ally])
    await assert_hp(walk, combat, {walk.player: 12, ally: 29 if combat else 40})
    if combat:
        walk.sd.combat_state = await walk.checkpoint()
        await set_hp(walk, ally, 10)
        await declare_defend(walk, walk.player, ally)
        assert [tick["healed"] for tick in effects(await walk.wrap())] == [1]
        await assert_hp(walk, True, {walk.player: 12, ally: 11})


async def scenario_ally_heal(world):
    async with ItemHealWalk(world.pool) as walk:
        await ally_heal(walk, False)


SCENARIOS = {GIFT: ("patron_passives:dawns_resilience", scenario_ally_heal, [()])}
