"""Patron healing synergies through registered spell and item commands."""

from unittest.mock import AsyncMock, patch

from _item_heal_fixtures import POTION, ItemHealWalk, heal_roll
from _spell_heal_fixtures import MASS, PRAYER, TOUCH, WOUNDS
from acceptance.seeds import seed_known_spells
from test_dawns_resilience import ORENTHEL, assert_gift, assert_hp, assert_hp_push
from test_spell_heal_landing import receipt

import db_mutations
import spells
from _gods_content import load_gods

MERCY = "orenthel_dawns_mercy"
THRESHOLD_HEALING = "mortaen_threshold_healing"
FINAL_MERCY = "mortaen_final_mercy"
CLAUSE = {"status": "active", "resolution": "engine", "implementation_id": MERCY}
KAELEN = {**ORENTHEL, "patron": "kaelen"}
MORTAEN = {**ORENTHEL, "patron": "mortaen"}
FULL_FOCUS = {"current": 30, "max": 30}


def assert_clause(row):
    assert row["type"] == "natural"
    (clause,) = row["clauses"]
    assert {key: clause.get(key) for key in CLAUSE} == CLAUSE


def test_authored_orenthel_heal_synergies():
    god = next(god for god in load_gods() if god["god_id"] == "orenthel")
    for archetype in ("cleric", "paladin"):
        assert_clause(god["layer_4_synergy_matrix"][archetype])


def test_authored_mortaen_heal_synergies() -> None:
    god = next(god for god in load_gods() if god["god_id"] == "mortaen")
    cleric, paladin = (god["layer_4_synergy_matrix"][key] for key in ("cleric", "paladin"))
    active = {"status": "active", "resolution": "engine"}
    assert cleric["type"] == "natural"
    assert cleric["clauses"] == [
        {**active, "effect": "Sacred Flame deals necrotic.", "implementation_id": "mortaen_threshold_mercy"},
        {
            **active,
            "effect": "Healing on 0 HP allies restores double. Best at pulling people back from the edge",
            "implementation_id": THRESHOLD_HEALING,
        },
    ]
    assert paladin["type"] == "divine"
    assert paladin["clauses"] == [
        {**active, "effect": "Healing an ally at 0 HP restores 1 additional HP.", "implementation_id": FINAL_MERCY}
    ]


async def prepare(walk, actor, archetype="cleric", *, wisdom=16, charisma=12, favor=ORENTHEL, hp=10):
    row = await walk.read(actor)
    await walk.patch_row(
        actor,
        **{"class": archetype},
        level=20,
        hp={"current": hp, "max": 20},
        focus=FULL_FOCUS,
        divine_favor=favor,
        attributes={**row["attributes"], "wisdom": wisdom, "charisma": charisma},
    )


def healed(target, gain, hp, *, modifier=3, bonus=3, rolled=5, maximum=20, implementation=MERCY):
    result = receipt(target, gain, hp, rolled=rolled, modifier=modifier, maximum=maximum)
    if bonus:
        result["synergy_components"] = [{"id": implementation, "bonus": bonus}]
    return result


async def cast_as(walk, combat, actor, target):
    if not combat:
        return await walk.command("activate", {"id": WOUNDS, "target_id": target}, actor=actor)
    declarations = [{"kind": "ability", "actor_id": actor, "action": WOUNDS, "targets": [target], "argument_type": ""}]
    declarations.extend(
        {"kind": "defend", "actor_id": p.id} for p in walk.fight_state.participants if p.id != actor and not p.is_fallen
    )
    await walk.command("declare_phase", {"declarations": declarations}, actor=actor)
    first = await walk.command("resolve_phase", {})
    packet = next(p["cast"] for p in first["packets"] if p["actor_id"] == actor)
    walk.sd.combat_state = await walk.checkpoint()
    if first["beat"] != "declaration":
        assert not any(p.get("cast") for p in await walk.wrap())
    return packet


async def single(walk, combat, archetype, wisdom, charisma, modifier, bonus):
    caster = walk.player
    target = await walk.add_player()
    await prepare(walk, caster, archetype, wisdom=wisdom, charisma=charisma)
    if archetype == "paladin":
        await seed_known_spells(walk.pool, caster, (WOUNDS,))
    if combat:
        state = await walk.fight()
        state.get_participant(caster).attributes["charisma"] = 8
        await walk.save()
    with heal_roll(5):
        packet = await cast_as(walk, combat, caster, target)
    gain = 5 + modifier + bonus
    await assert_hp(walk, combat, {target: 3 + gain, caster: 12})
    assert packet["healing_results"] == [healed(target, gain, 3 + gain, modifier=modifier, bonus=bonus)]
    assert_gift(packet, [target])
    assert await walk.focus() == 30 - spells.get_spell(WOUNDS).focus_cost
    assert_clause((await walk.command("query_info", {"kind": "patron"}))["synergy"])

    if archetype == "paladin":
        await prepare(walk, caster, archetype, wisdom=8, charisma=8)
        await walk.patch_row(target, hp={"current": 3, "max": 20})
        if combat:
            await walk.fight()
        with heal_roll(5):
            packet = await cast_as(walk, combat, caster, target)
        await assert_hp(walk, combat, {target: 7, caster: 12})
        assert packet["healing_results"] == [healed(target, 4, 7, modifier=-1, bonus=0)]


async def group(walk, combat, spell):
    await prepare(walk, walk.player, hp=20)
    await seed_known_spells(walk.pool, walk.player, (spell,))
    first, second = [await walk.add_player() for _ in range(2)]
    full = await walk.add_player(hp=20)
    targets = [first, second, first, full] if spell == PRAYER else None
    if combat:
        await walk.fight()
    with (
        heal_roll(5) as roll,
        patch.object(db_mutations, "update_player_hp", wraps=db_mutations.update_player_hp) as hp,
    ):
        packet = await walk.cast(spell, targets=targets, combat=combat)
    roll.assert_called_once_with("2d8")
    expected = [healed(first, 11, 14), healed(second, 11, 14), healed(full, 0, 20)]
    if spell == MASS:
        expected.append(healed(walk.player, 0, 20))
    await assert_hp(walk, combat, {first: 14, second: 14, full: 20, walk.player: 20})
    assert sorted(packet["healing_results"], key=lambda r: r["target_id"]) == sorted(
        expected, key=lambda r: r["target_id"]
    )
    assert {call.args[0] for call in hp.await_args_list} == {first, second}
    assert await walk.focus() == 30 - spells.get_spell(spell).focus_cost
    if not combat:
        assert_hp_push(walk, first, 14)
        assert_hp_push(walk, second, 14)
        assert not any(
            call.kwargs.get("destination_identities") == [full]
            for call in walk.sd.room.local_participant.publish_data.await_args_list
        )


async def scope(walk, combat):
    caster = walk.player
    target = await walk.add_player()
    for archetype, favor, spell, gain, bonus in [
        ("cleric", ORENTHEL, WOUNDS, 11, 3),
        ("cleric", ORENTHEL, None, 7, 0),
        ("cleric", KAELEN, WOUNDS, 8, 0),
        ("druid", ORENTHEL, TOUCH, 8, 0),
    ]:
        await prepare(walk, caster, archetype, favor=favor)
        await walk.patch_row(target, hp={"current": 3, "max": 20})
        if combat:
            await walk.fight()
        if spell:
            with heal_roll(5):
                packet = await walk.cast(spell, targets=[target], combat=combat)
            result = healed(target, gain, 3 + gain, bonus=bonus)
        else:
            await walk.put()
            with heal_roll(7):
                if combat:
                    await walk.declare_item(target=target)
                    packet = await walk.resolve_item()
                    await walk.wrap()
                else:
                    inventory = await walk.command("query_info", {"kind": "inventory"})
                    potion = next(i for i in inventory["items"] if i["id"] == POTION)
                    packet = await walk.command("activate", {"id": potion["consume_id"], "target_id": target})
            assert packet["remaining_quantity"] == await walk.quantity() == 1
            assert await walk.focus() == 30
            result = healed(target, gain, 3 + gain, modifier=0, bonus=0, rolled=7)
        await assert_hp(walk, combat, {target: 3 + gain})
        assert packet["healing_results"] == [result]


async def guest_authority(walk, combat):
    host, guest, target = walk.player, await walk.add_player(), await walk.add_player()
    walk.sd.patron_id = "kaelen"
    for actor, idle, favor, gain, bonus in [(guest, host, ORENTHEL, 11, 3), (host, guest, KAELEN, 8, 0)]:
        await prepare(walk, host, favor=KAELEN)
        await prepare(walk, guest)
        await walk.patch_row(target, hp={"current": 3, "max": 20})
        if combat:
            await walk.fight()
        with heal_roll(5):
            packet = await cast_as(walk, combat, actor, target)
        await assert_hp(walk, combat, {target: 3 + gain, guest: 12 if favor == ORENTHEL else 10})
        assert packet["healing_results"] == [healed(target, gain, 3 + gain, bonus=bonus)]
        assert (await walk.read(actor))["focus"]["current"] == 30 - spells.get_spell(WOUNDS).focus_cost
        assert (await walk.read(idle))["focus"]["current"] == 30
        if favor == ORENTHEL:
            assert_gift(packet, [target])


async def set_fallen(walk: ItemHealWalk, target: str, maximum: int = 20) -> None:
    participant = walk.fight_state.get_participant(target)
    assert participant is not None
    participant.hp_current = 0
    participant.hp_max = maximum
    participant.is_fallen = True
    participant.death_save_successes, participant.death_save_failures = 1, 2
    await walk.save()


async def assert_revived(walk: ItemHealWalk, target: str) -> None:
    participant = (await walk.checkpoint()).get_participant(target)
    assert participant is not None
    assert (participant.is_fallen, participant.death_save_successes, participant.death_save_failures) == (False, 0, 0)


async def mortaen_single(walk: ItemHealWalk, before: int, maximum: int, gain: int, bonus: int) -> None:
    await prepare(walk, walk.player, favor=MORTAEN, hp=20)
    # A stale positive player row makes the combat snapshot the only evidence of the fall.
    target = await walk.add_player(hp=5 if before == 0 and maximum == 20 else before)
    if maximum != 20:
        await walk.patch_row(target, maxhp_override=maximum - 20)
    await walk.fight()
    if before == 0:
        await set_fallen(walk, target, maximum)
    with heal_roll(5):
        packet = await cast_as(walk, True, walk.player, target)
    await assert_hp(walk, True, {target: before + gain})
    if before == 0:
        await assert_revived(walk, target)
    assert (await walk.read(target))["hp"]["max"] == 20
    assert packet["healing_results"] == [
        healed(target, gain, before + gain, bonus=bonus, maximum=maximum, implementation=THRESHOLD_HEALING)
    ]


async def mortaen_group(walk: ItemHealWalk) -> None:
    caster = walk.player
    await prepare(walk, caster, favor=MORTAEN, hp=20)
    await seed_known_spells(walk.pool, caster, (MASS,))
    fallen, standing = await walk.add_player(hp=0), await walk.add_player(hp=5)
    await walk.fight()
    await set_fallen(walk, fallen)
    with heal_roll(5) as roll:
        packet = await walk.cast(MASS, combat=True)
    roll.assert_called_once_with("2d8")
    await assert_hp(walk, True, {fallen: 16, standing: 13, caster: 20})
    await assert_revived(walk, fallen)
    expected = [
        healed(fallen, 16, 16, bonus=8, implementation=THRESHOLD_HEALING),
        healed(standing, 8, 13, bonus=0),
        healed(caster, 0, 20, bonus=0),
    ]
    assert sorted(packet["healing_results"], key=lambda r: r["target_id"]) == sorted(
        expected, key=lambda r: r["target_id"]
    )


async def mortaen_paladin(walk: ItemHealWalk) -> None:
    caster = walk.player
    await prepare(walk, caster, "paladin", favor=MORTAEN, hp=20)
    await seed_known_spells(walk.pool, caster, (WOUNDS,))
    target = await walk.add_player()
    room = walk.sd.room
    assert room is not None
    publish_data = room.local_participant.publish_data
    assert isinstance(publish_data, AsyncMock)
    for before, gain, bonus in [(0, 9, 1), (1, 8, 0)]:
        await walk.patch_row(caster, focus=FULL_FOCUS)
        await walk.patch_row(target, hp={"current": before, "max": 20})
        publish_data.reset_mock()
        with heal_roll(5):
            packet = await cast_as(walk, False, caster, target)
        await assert_hp(walk, False, {target: 9})
        assert packet["healing_results"] == [healed(target, gain, 9, bonus=bonus, implementation=FINAL_MERCY)]
        assert_hp_push(walk, target, 9)


async def mortaen_item(walk: ItemHealWalk) -> None:
    await prepare(walk, walk.player, favor=MORTAEN, hp=20)
    target = await walk.add_player(hp=0)
    await walk.put()
    await walk.fight()
    await set_fallen(walk, target)
    with heal_roll(7):
        await walk.declare_item(target=target)
        packet = await walk.resolve_item()
        await walk.wrap()
    await assert_hp(walk, True, {target: 7})
    await assert_revived(walk, target)
    assert packet["healing_results"] == [receipt(target, 7, 7, rolled=7, modifier=0)]
    assert packet["remaining_quantity"] == await walk.quantity() == 1
    assert await walk.focus() == 30


async def scenario(world, check, *args):
    async with ItemHealWalk(world.pool) as walk:
        await check(walk, *args)


SCENARIOS = {
    MERCY: (
        "patron_synergy_heal:bonus_components",
        scenario,
        [
            (single, combat, archetype, wisdom, charisma, modifier, bonus)
            for combat in (False, True)
            for archetype, wisdom, charisma, modifier, bonus in [
                ("cleric", 16, 12, 3, 3),
                ("paladin", 10, 18, 0, 4),
            ]
        ]
        + [(group, combat, spell) for combat, spell in [(False, MASS), (True, MASS), (False, PRAYER)]]
        + [(check, combat) for check in (scope, guest_authority) for combat in (False, True)],
    ),
    THRESHOLD_HEALING: (
        "patron_synergy_heal:bonus_components",
        scenario,
        [
            (mortaen_single, 0, 20, 16, 8),
            (mortaen_single, 0, 15, 15, 8),
            (mortaen_single, 1, 20, 8, 0),
            (mortaen_group,),
            (mortaen_item,),
        ],
    ),
    FINAL_MERCY: ("patron_synergy_heal:bonus_components", scenario, [(mortaen_paladin,)]),
}
