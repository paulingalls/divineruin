"""Cleansing Touch through registered spell, combat and item commands."""

from unittest.mock import patch

import pytest
from _item_heal_fixtures import ItemHealWalk, heal_roll
from _item_heal_fixtures import item_heal_walk as item_heal_walk
from _spell_heal_fixtures import REGENERATE, TOUCH
from acceptance.seeds import seed_known_spells
from sample_fixtures import published_payloads
from test_dawns_resilience import ORENTHEL, assert_gift, assert_hp
from test_heal_synergies import scenario
from test_spell_heal_landing import receipt

import combat_spell_heal
import db_mutations_resonance
import resonance_events
from _gods_content import load_gods
from caster_state import ResonanceTrack
from session_data import SessionData

CLEANSING = "orenthel_cleansing_touch"
COMPONENT = {"id": CLEANSING, "resonance_removed": 1}


def test_authored_cleansing_touch() -> None:
    god = next(god for god in load_gods() if god["god_id"] == "orenthel")
    for archetype in ("druid", "beastcaller"):
        assert god["layer_4_synergy_matrix"][archetype] == {
            "type": "unexpected",
            "name": "Cleansing Touch",
            "clauses": [
                {
                    "effect": "Healing Touch also removes 1 Resonance from target. Active party Resonance management",
                    "status": "active",
                    "resolution": "engine",
                    "implementation_id": CLEANSING,
                }
            ],
        }


async def set_resonance(walk: ItemHealWalk, pid: str, total: int) -> None:
    await walk.patch_row(pid, resonance={"current": total, "flickering_bonus": 1})
    track = walk.sd.member_state(pid).resonance
    track.current = total
    track.flickering_bonus = 1


async def prepare(walk: ItemHealWalk, *, archetype: str = "druid", spell: str = TOUCH, patron: dict = ORENTHEL) -> None:
    await walk.prepare(spell)
    await walk.patch(**{"class": archetype}, divine_favor=patron)
    await set_resonance(walk, walk.player, 2)


def resonance_payloads(walk: ItemHealWalk) -> list[dict]:
    return [p for p in published_payloads(walk.sd.room) if p["type"] == "resonance_changed"]


async def observe_resonance(walk: ItemHealWalk, pid: str) -> tuple[int, int]:
    data = (await walk.read(pid))["resonance"]
    track = walk.sd.member_state(pid).resonance
    assert data["flickering_bonus"] == track.flickering_bonus == 1
    return data["current"], track.current


async def cast(walk: ItemHealWalk, target: str, combat: bool, *, spell: str = TOUCH) -> dict:
    with heal_roll(5):
        if combat:
            phase = await walk.command("resolve_phase", {})
            return next(p["cast"] for p in phase["packets"] if p["actor_id"] == walk.player)
        return await walk.cast(spell, targets=[target])


def observe_publications(walk: ItemHealWalk, observed: list[tuple[str, tuple[int, int], int]]):
    publish = resonance_events.publish_resonance_changed

    async def observe(session: SessionData, *, resonance_track: ResonanceTrack, caster_id: str) -> None:
        observed.append((caster_id, await observe_resonance(walk, caster_id), resonance_track.current))
        await publish(session, resonance_track=resonance_track, caster_id=caster_id)

    return patch.object(resonance_events, "publish_resonance_changed", side_effect=observe)


async def cleanses(
    walk: ItemHealWalk, combat: bool, archetype: str, self_cast: bool, start: int, *, full_hp: bool = False
) -> None:
    await prepare(walk, archetype=archetype)
    target = walk.player if self_cast else await walk.add_player(hp=20 if full_hp else 3)
    await set_resonance(walk, target, start)
    if self_cast:
        walk.sd.member_state(walk.player).corruption_level = 2
    if combat:
        await walk.fight()
        await walk.declare(TOUCH, [target])
    observed = []
    with observe_publications(walk, observed):
        packet = await cast(walk, target, combat)
    assert packet["resonance_generated"] == 0
    final = start + packet["resonance_generated"] - 1
    assert await observe_resonance(walk, target) == (final, final)
    assert observed == [(target, (final, final), final)]
    assert resonance_payloads(walk) == [{"type": "resonance_changed", "state": "stable", "caster_id": target}]
    gain, hp = (0, 20) if full_hp else (8, 11)
    assert packet["healing_results"] == [receipt(target, gain, hp) | {"synergy_components": [COMPONENT]}]
    expected_hp = {target: hp}
    if not self_cast:
        assert await observe_resonance(walk, walk.player) == (2, 2)
        if full_hp:
            assert "gift_triggered" not in packet
        else:
            assert_gift(packet, [target], hp=5)
            expected_hp[walk.player] = 5
    await assert_hp(walk, combat, expected_hp)
    if combat and not self_cast:
        assert not any(p.get("cast") for p in await walk.wrap())
        assert await observe_resonance(walk, target) == (final - 1, final - 1)


SCENARIOS = {
    CLEANSING: (
        "patron_synergy_heal:for_cast",
        scenario,
        [
            (cleanses, combat, "druid", self_cast, 2 if self_cast else 3)
            for combat in (False, True)
            for self_cast in (False, True)
        ]
        + [(cleanses, False, "beastcaller", False, 2)],
    ),
}


async def test_cleansing_full_hp_crosses_the_resonance_threshold(walk: ItemHealWalk) -> None:
    await cleanses(walk, False, "druid", False, 6, full_hp=True)


@pytest.mark.parametrize("mage_first", [True, False])
async def test_cleansing_composes_with_an_ally_cast(walk: ItemHealWalk, mage_first: bool) -> None:
    await prepare(walk)
    ally = await walk.add_player()
    spell = "arcane_detect_magic"
    await walk.patch_row(ally, **{"class": "mage"}, level=20, divine_favor=None, focus={"current": 10, "max": 10})
    await seed_known_spells(walk.pool, ally, (spell,))
    await set_resonance(walk, ally, 2)
    state = await walk.fight()
    actors = [ally, walk.player] if mage_first else [walk.player, ally]
    state.initiative_order = [*actors, "foe"]
    for index, pid in enumerate(actors):
        participant = state.get_participant(pid)
        assert participant is not None
        participant.initiative = 20 - index
    await walk.save()
    await walk.command(
        "declare_phase",
        {
            "declarations": [
                {"kind": "ability", "actor_id": walk.player, "action": TOUCH, "targets": [ally], "argument_type": ""},
                {"kind": "ability", "actor_id": ally, "action": spell, "targets": [], "argument_type": ""},
            ]
        },
    )
    observed = []
    with heal_roll(5), observe_publications(walk, observed):
        phase = await walk.command("resolve_phase", {})
    casts = {p["actor_id"]: p["cast"] for p in phase["packets"] if "cast" in p}
    assert list(casts) == actors
    generated = casts[ally]["resonance_generated"]
    assert generated > 0
    final = 2 + generated - 1
    assert await observe_resonance(walk, ally) == (final, final)
    assert observed == [(ally, (final, final), final)]
    assert casts[walk.player]["healing_results"] == [receipt(ally, 8, 11) | {"synergy_components": [COMPONENT]}]
    assert resonance_payloads(walk) == [
        {"type": "resonance_changed", "state": walk.sd.member_state(ally).resonance.state, "caster_id": ally}
    ]


@pytest.mark.parametrize("combat,legacy", [(False, False), (True, False), (False, True)])
async def test_zero_resonance_needs_no_write(walk: ItemHealWalk, combat: bool, legacy: bool) -> None:
    await prepare(walk)
    ally = await walk.add_player()
    await set_resonance(walk, ally, 0)
    if legacy:
        await walk.patch_row(ally, resonance={"flickering_bonus": 1})
    if combat:
        await walk.fight()
        await walk.declare(TOUCH, [ally])
    with patch.object(
        db_mutations_resonance, "update_player_resonance", wraps=db_mutations_resonance.update_player_resonance
    ) as write:
        packet = await cast(walk, ally, combat)
    write.assert_not_awaited()
    if legacy:
        assert (await walk.read(ally))["resonance"] == {"flickering_bonus": 1}
        assert walk.sd.member_state(ally).resonance.current == 0
    else:
        assert await observe_resonance(walk, ally) == (0, 0)
    assert resonance_payloads(walk) == []
    assert packet["healing_results"] == [receipt(ally, 8, 11)]
    await assert_hp(walk, combat, {ally: 11})


async def test_beastcaller_heals_companion_without_cleansing(walk: ItemHealWalk) -> None:
    await prepare(walk, archetype="beastcaller")
    ally = await walk.add_player()
    await set_resonance(walk, ally, 3)
    await walk.fight(companion=True)
    await walk.declare(TOUCH, ["companion"])
    with patch.object(
        db_mutations_resonance, "remove_player_resonance", wraps=db_mutations_resonance.remove_player_resonance
    ) as remove:
        packet = await cast(walk, "companion", True)
    remove.assert_not_awaited()
    assert packet["healing_results"] == [receipt("companion", 8, 11)]
    await assert_hp(walk, True, {"companion": 11})
    assert await observe_resonance(walk, walk.player) == (2, 2)
    assert await observe_resonance(walk, ally) == (3, 3)
    assert resonance_payloads(walk) == []


@pytest.mark.parametrize(
    "spell,patron,healed,rolled,modifier",
    [(REGENERATE, ORENTHEL, 17, 5, 0), (TOUCH, {**ORENTHEL, "patron": "kaelen"}, 8, 5, 3), (None, ORENTHEL, 7, 7, 0)],
)
async def test_other_healing_does_not_cleanse(
    walk: ItemHealWalk, spell: str | None, patron: dict, healed: int, rolled: int, modifier: int
) -> None:
    await prepare(walk, spell=spell or TOUCH, patron=patron)
    ally = await walk.add_player()
    await set_resonance(walk, ally, 3)
    if spell is None:
        await walk.put()
        with heal_roll(rolled):
            packet = await walk.consume(target=ally)
    else:
        packet = await cast(walk, ally, False, spell=spell)
        assert packet["resonance_generated"] == (2 if patron["patron"] == "kaelen" else 0)
    if patron == ORENTHEL:
        assert_gift(packet, [ally], hp=5)
    assert await observe_resonance(walk, ally) == (3, 3)
    assert not any(event["caster_id"] == ally for event in resonance_payloads(walk))
    assert packet["healing_results"] == [receipt(ally, healed, 3 + healed, rolled=rolled, modifier=modifier)]
    await assert_hp(walk, False, {ally: 3 + healed})


@pytest.mark.parametrize("combat", [False, True])
async def test_cleansing_rolls_back_with_hp(walk: ItemHealWalk, combat: bool) -> None:
    await prepare(walk)
    ally = await walk.add_player()
    await set_resonance(walk, ally, 3)
    if combat:
        await walk.fight()
        await walk.declare(TOUCH, [ally])

    async def snapshot() -> tuple:
        return (
            await walk.row(),
            await walk.read(ally),
            walk.sd.party.to_dict(),
            (await walk.checkpoint()).to_dict() if combat else None,
            published_payloads(walk.sd.room),
            walk.sd.event_bus.drain(),
        )

    before = await snapshot()
    lander = "land" if combat else "land_exploration"
    land = getattr(combat_spell_heal, lander)
    observed = []

    async def fail_after_heal(*args, **kwargs) -> None:
        await land(*args, **kwargs)
        staged = await walk.read(ally, conn=kwargs["conn"])
        observed.append((staged["hp"]["current"], staged["resonance"]["current"]))
        assert await observe_resonance(walk, ally) == (3, 3)
        assert walk.sd.party.to_dict() == before[2]
        assert published_payloads(walk.sd.room) == before[4]
        assert walk.sd.event_bus.qsize == 0
        raise ConnectionError("injected failure after Cleansing Touch")

    with heal_roll(5), patch.object(combat_spell_heal, lander, side_effect=fail_after_heal):
        if combat:
            await walk.command("resolve_phase", {}, error=True)
        else:
            await walk.command("activate", {"id": TOUCH, "target_id": ally}, error=True)

    assert observed == [(11, 2)]
    assert await snapshot() == (*before[:-1], [])
