"""Weapon training through registered equip and combat commands."""

import json
from collections.abc import Iterator
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.attribute_increase_walk import IncreaseWalk
from acceptance.mawling_harness import MawlingHarness
from acceptance.seeds import seed_known_spells
from acceptance.test_architect_entomb import favor
from acceptance.test_equip_and_electives import call, enter_fight
from acceptance.test_martial_core_kit import adjacent_foe, declare, weapon_attack
from acceptance.test_opportunity_strike import STRIKE, advance_to_departure, reconnect
from acceptance.test_opportunity_strike import fight as fight
from acceptance.test_still_anchors import fresh_session
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory

import ability_persistence
import archetypes
import conditions
import event_types as E
from creation_classes import CLASSES
from inventory_tools import transact
from mode_tools import enter_mode

GREATSWORD = "greatsword_steel"
SOURCE = "weapon_proficiency"


async def setup(harness: SimpleNamespace, archetype: str, level: int = 3) -> IncreaseWalk:
    walk = await IncreaseWalk().setup(harness, tools=[transact, enter_mode])
    await walk.seed(level, archetype)
    return walk


async def equip(walk: IncreaseWalk, item: str) -> str:
    await call(walk, "transact", action="exchange", item_id=item, delta=1)
    result = await call(walk, "transact", action="equip", item_id=item, delta=0)
    assert result["action"] == "equipped"
    assert (await walk.row())["equipment"]["main_hand"]["id"] == item
    return result["narration_cue"]


@pytest.mark.parametrize("archetype", ["mage", "warrior"])
def test_equip_cue(harness: SimpleNamespace, archetype: str) -> None:
    async def check() -> None:
        cue = await equip(await setup(harness, archetype), GREATSWORD)
        if archetype == "mage":
            assert "Tell the player" in cue and "not proficient" in cue and "disadvantage" in cue
        else:
            assert "proficient" not in cue and "disadvantage" not in cue

    harness.run_sync(check())


async def declare_weapon(fight: MawlingHarness, foe: str, weapon: str) -> None:
    actor = fight.players[0]
    state = await fight.reload()
    await fight.command(
        "declare_phase",
        {
            "declarations": [
                {**weapon_attack(actor, foe, ""), "action": weapon},
                *({"kind": "defend", "actor_id": pid, "reshape": []} for pid in state.initiative_order if pid != actor),
            ],
        },
    )


async def assert_attack(
    walk: IncreaseWalk,
    fight: MawlingHarness,
    foe: str,
    weapon: str,
    faces: tuple[int, ...],
    kept: int,
    source: str | None,
) -> None:
    await declare_weapon(fight, foe, weapon)
    walk.events.clear()
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(face) for face in (*faces, 20)]) as rolls,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        packets = await fight.drain()
    (attack,) = [packet for packet in packets if packet.get("action") == weapon]
    assert [call.args for call in rolls.call_args_list] == [("d20",)] * len(faces)
    assert attack["roll"] == kept
    assert attack.get("attack_disadvantage_source") == source
    (event,) = [event for event in walk.events if event["type"] == E.DICE_ROLL]
    assert event["roll"] == kept


@pytest.mark.parametrize("variant", ["equipped", "advantage", "legacy-id", "legacy-starter", "rapier", "dagger"])
def test_weapon_roll_and_reload(harness: SimpleNamespace, variant: str) -> None:
    async def check() -> None:
        rogue = variant in {"rapier", "dagger"}
        walk = await setup(harness, "rogue" if rogue else "mage")
        if variant == "rapier":
            assert "disadvantage" not in await equip(walk, "rapier_dueling")
        elif variant != "dagger":
            await equip(walk, GREATSWORD)
        row = await walk.row()
        weapon = row["equipment"]["main_hand"]
        if variant == "legacy-starter":
            weapon = CLASSES["warrior"].starting_equipment["main_hand"]
        if variant in {"legacy-id", "legacy-starter", "dagger"}:
            row["equipment"]["main_hand"] = {
                key: value
                for key, value in weapon.items()
                if key in {"id", "name", "damage", "damage_type", "properties"}
            }
            await walk.pool.execute(
                "UPDATE players SET data=$2::jsonb WHERE player_id=$1", walk.player, json.dumps(row)
            )
        fight = await enter_fight(walk)
        harness.stack.callback(lambda: harness.run_sync(fight.session.aclose()))
        foe = await adjacent_foe(fight)
        if variant in {"legacy-id", "legacy-starter", "dagger"}:
            await fresh_session(fight, await fight.reload())
        if variant == "advantage":
            state = await fight.reload()
            actor = state.get_participant(walk.player)
            assert actor is not None
            actor.conditions = conditions.apply_condition(actor.conditions, "precise_strike", source=actor.id)
            await fight.persist()
        faces, kept = ((17,), 17) if rogue or variant == "advantage" else ((17, 3), 3)
        await assert_attack(walk, fight, foe, weapon["name"], faces, kept, None if rogue else SOURCE)
        if variant == "equipped":
            await fresh_session(fight, await fight.reload())
            await assert_attack(walk, fight, foe, weapon["name"], (18, 4), 4, SOURCE)

    harness.run_sync(check())


def test_blade_flurry_rolls_each_swing_at_disadvantage(harness: SimpleNamespace) -> None:
    async def check() -> None:
        walk = await setup(harness, "rogue", level=10)
        await equip(walk, GREATSWORD)
        await ability_persistence.set_elective_equipped(walk.player, "rogue_blade_flurry", True, conn=walk.pool)
        fight = await enter_fight(walk)
        foe = await adjacent_foe(fight)
        await declare(fight, "rogue_blade_flurry", [foe])
        with (
            patch("check_resolution.dice_roll", side_effect=[_d20(face) for face in (17, 3, 18, 4, 19, 5)]) as rolls,
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
        ):
            packets = await fight.drain()
        (flurry,) = [packet for packet in packets if packet.get("actor_id") == walk.player and "attacks" in packet]
        assert rolls.call_count == 6
        assert [(swing["roll"], swing["attack_disadvantage_source"]) for swing in flurry["attacks"]] == [
            (3, SOURCE),
            (4, SOURCE),
            (5, SOURCE),
        ]

    harness.run_sync(check())


@pytest.fixture(params=[True, False], ids=["trained", "untrained"])
def warrior_training(fight: MawlingHarness, request: pytest.FixtureRequest) -> Iterator[bool]:
    if request.param:
        yield True
        return
    original = {archetype: archetypes.get_archetype_chassis(archetype) for archetype in CLASSES}
    archetypes.set_archetypes({**original, "warrior": replace(original["warrior"], weapon_proficiencies=("simple",))})
    try:
        yield False
    finally:
        archetypes.set_archetypes(original)


async def test_opportunity_rolls_with_snapshotted_weapon(fight: MawlingHarness, warrior_training: bool) -> None:
    warrior = fight.players[0]
    waiting = (await advance_to_departure(fight))["next"]["waiting_on"]
    assert [(row["actor_id"], row["id"]) for row in waiting["reactions"]] == [(warrior, STRIKE)]
    await reconnect(fight)
    await fight.command("activate", {"id": STRIKE})
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(face) for face in (17, 3, 18)]) as rolls,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        result = await fight.command("resolve_phase", {})
    (reaction,) = [packet for packet in result["packets"] if packet.get("reaction") == STRIKE]
    assert rolls.call_count == (2 if warrior_training else 3)
    assert reaction["roll"] == (17 if warrior_training else 3)
    assert reaction.get("attack_disadvantage_source") == (None if warrior_training else SOURCE)


def test_fate_keeps_prepared_disadvantage_after_reload(harness: SimpleNamespace) -> None:
    async def check() -> None:
        walk = await setup(harness, "mage")
        await equip(walk, GREATSWORD)
        fight = await enter_fight(walk)
        harness.stack.callback(lambda: harness.run_sync(fight.session.aclose()))
        foe = await adjacent_foe(fight)
        state = await fight.reload()
        target = state.get_participant(foe)
        assert target is not None
        target.ac = 5
        await fight.persist()
        await favor(fight)
        await declare_weapon(fight, foe, "Steel Greatsword")
        with (
            patch("check_resolution.dice_roll", side_effect=[_d20(17), _d20(11)]) as rolls,
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)) as damage,
        ):
            offer = (await fight.command("resolve_phase", {}))["fate_offer"]
            assert (offer["roller_id"], offer["die"], rolls.call_count) == (walk.player, 11, 2)
            damage.assert_not_called()
            await fresh_session(fight, await fight.reload())
            packets = await fight.drain()
        assert rolls.call_count == 2
        damage.assert_called_once()
        (attack,) = [packet for packet in packets if packet.get("action") == "Steel Greatsword"]
        assert attack["roll"] == 11 and attack["attack_disadvantage_source"] == SOURCE
        target = (await fight.reload()).get_participant(foe)
        assert target is not None and target.hp_current == 100 - attack["damage"]

    harness.run_sync(check())


def test_spell_attack_ignores_equipped_weapon_proficiency(harness: SimpleNamespace) -> None:
    async def check() -> None:
        walk = await setup(harness, "mage")
        await equip(walk, GREATSWORD)
        await seed_known_spells(walk.pool, walk.player, ("arcane_bolt",))
        fight = await enter_fight(walk)
        foe = await adjacent_foe(fight)
        await declare(fight, "arcane_bolt", [foe])
        with (
            patch("check_resolution.dice_roll", return_value=_d20(17)) as rolls,
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
        ):
            packets = await fight.drain()
        (cast,) = [packet["cast"] for packet in packets if packet.get("action") == "arcane_bolt"]
        attack = cast["damage_result"]
        rolls.assert_called_once()
        assert attack["roll"] == 17 and "attack_disadvantage_source" not in attack

    harness.run_sync(check())
