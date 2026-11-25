from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from _aelora_hearthfire_fixtures import COMPANION, GIFT, fall, healing_rolls, hearth, point, snapshot
from _mortaen_threshold_fixtures import FOE, active, claw, declare, events
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from acceptance._capstone_helpers import _d20, _damage_die
from test_patron_engine_valdris import checkpoint, reload_state
from voice_condition_fixtures import participant

import check_resolution_save
import event_types as E
from concentration_break import break_concentration_on_damage
from conditions import apply_condition, has_condition
from db_mutations_concentration import read_player_concentration, update_player_concentration
from zhael_fate import FATE

SPELL = "divine_bless"


async def light_hearth(world: SimpleNamespace, call: Any) -> None:
    await call("activate", id=GIFT)
    assert (await row(world, 0))["patron_gifts"][GIFT] == {"spent": True}
    assert (await reload_state(world)).hearthfire_zones == [
        {
            "source_id": world.ids[0],
            "center": point(5),
            "radius_ft": 15,
            "rounds_remaining": 3,
            "admitted_ids": [],
            "failed_rounds": {},
        }
    ]


async def keep_original(world: SimpleNamespace, call: Any, offer: dict) -> dict:
    session = world.ctx.userdata
    with session._bind_authenticated_actor(world.ids[1], 1, lambda *_: None):
        return await call("activate", id=FATE, offer_id=offer["offer_id"], keep="original")


async def start_concentration(world: SimpleNamespace) -> None:
    guest = world.ids[1]
    world.ctx.userdata.member_state(guest).concentration.spell_id = SPELL
    await update_player_concentration(guest, SPELL, conn=world.pool)


async def assert_concentration(world: SimpleNamespace, holds: bool) -> None:
    guest = world.ids[1]
    expected = SPELL if holds else None
    assert world.ctx.userdata.member_state(guest).concentration.spell_id == expected
    assert await read_player_concentration(guest, conn=world.pool) == {"spell_id": expected}


@pytest.mark.parametrize("inside", [True, False], ids=["inside", "outside"])
async def test_encounter_effect_save(world: SimpleNamespace, inside: bool) -> None:
    async with hearth(world) as call:
        await light_hearth(world, call)
        guest = world.ids[1]
        state = active(world)
        state.spatial["positions"][guest] = point(5, 15 if inside else 15.01)
        participant(state, FOE).action_pool = [
            {"name": "Poisoning Strike", "save": "CON", "dc": 10, "applies_condition": "poisoned"}
        ]
        await checkpoint(world)
        await declare(
            world,
            call,
            {
                "kind": "ability",
                "actor_id": FOE,
                "action": "Poisoning Strike",
                "targets": [guest],
                "argument_type": "",
                "reshape": [],
            },
        )
        await call("resolve_phase")
        face = 18 if inside else 3
        with patch("check_resolution.dice_roll", side_effect=[_d20(3), _d20(18)]) as dice:
            await call("resolve_phase")
            assert active(world).open_window["stage"] == "pre_roll"
            offer = (await call("resolve_phase"))["fate_offer"]
            assert (offer["roller_id"], offer["die"], offer["total"]) == (guest, face, face)
            result = await keep_original(world, call, offer)
            assert dice.call_count == (2 if inside else 1)
        packet = next(packet for packet in result["packets"] if packet.get("actor_id") == FOE)
        assert (packet["save_roll"], packet["save_total"], packet["save_success"]) == (face, face, inside)
        assert has_condition(participant(await reload_state(world), guest).conditions, "poisoned") is (not inside)


@pytest.mark.parametrize("location", ["inside", "outside", "no-zone", "out-of-combat"])
async def test_voice_check_save(world: SimpleNamespace, location: str) -> None:
    async with hearth(world) as call:
        guest = world.ids[1]
        if location in {"inside", "outside"}:
            await light_hearth(world, call)
        if location == "outside":
            active(world).spatial["positions"][guest] = point(5, 15.01)
            await checkpoint(world)
        inside = location == "inside"
        face = 18 if inside else 3
        session = world.ctx.userdata
        state = session.combat_state
        if location == "out-of-combat":
            session.combat_state = None
        try:
            with (
                session._bind_authenticated_actor(guest, 1, lambda *_: None),
                patch("check_resolution.dice_roll", side_effect=[_d20(3), _d20(18)]) as dice,
            ):
                offer = (
                    await call(
                        "check",
                        roll={
                            "kind": "save",
                            "save_type": "constitution",
                            "dc": 10,
                            "effect_on_fail": "poisoned",
                        },
                    )
                )["fate_offer"]
                assert (offer["roller_id"], offer["die"], offer["total"]) == (guest, face, face)
                result = await keep_original(world, call, offer)
                assert dice.call_count == (2 if inside else 1)
        finally:
            if location == "out-of-combat":
                session.combat_state = state
        assert (result["roll"], result["total"], result["outcome"]) == (
            face,
            face,
            "success" if inside else "failure",
        )
        [event] = [e for e in events(world) if e["type"] == E.DICE_ROLL and e["roll_type"] == "saving_throw"]
        assert (event["roll"], event["total"], event["success"]) == (face, face, inside)


@pytest.mark.parametrize("inside", [True, False], ids=["inside", "outside"])
async def test_damage_concentration_save(world: SimpleNamespace, inside: bool) -> None:
    async with hearth(world) as call:
        await light_hearth(world, call)
        guest = world.ids[1]
        state = active(world)
        state.spatial["positions"].update({guest: point(5, 15 if inside else 15.01), FOE: point(4, 15)})
        await start_concentration(world)
        strike = {**claw(world), "target_id": guest}
        await checkpoint(world)
        await declare(world, call, strike)
        await call("resolve_phase")
        face = 18 if inside else 3
        with (
            patch("check_resolution.dice_roll", side_effect=[_d20(19), _d20(3), _d20(18)]) as dice,
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
        ):
            await call("resolve_phase")
            assert active(world).open_window["stage"] == "pre_roll"
            attack = (await call("resolve_phase"))["fate_offer"]
            assert (attack["roller_id"], attack["die"], dice.call_count) == (FOE, 19, 1)
            offer = (await keep_original(world, call, attack))["fate_offer"]
            assert (offer["roller_id"], offer["die"], offer["total"]) == (guest, face, face)
            assert 0 < participant(active(world), guest).hp_current < 30
            await keep_original(world, call, offer)
            assert dice.call_count == (3 if inside else 2)
        await assert_concentration(world, inside)


@pytest.mark.parametrize("working_state", [True, False], ids=["working", "live-fallback"])
async def test_concentration_uses_effective_state(world: SimpleNamespace, working_state: bool) -> None:
    async with hearth(world) as call:
        await light_hearth(world, call)
        session = world.ctx.userdata
        guest = world.ids[1]
        working = deepcopy(active(world))
        if working_state:
            active(world).spatial["positions"][guest] = point(5, 15.01)
            await checkpoint(world)
        await start_concentration(world)
        saved = []
        resolve = check_resolution_save.resolve_saving_throw

        def observe(*args: Any, **kwargs: Any) -> check_resolution_save.SavingThrowResult:
            result = resolve(*args, **kwargs)
            saved.append(result.roll)
            return result

        with (
            patch.object(check_resolution_save, "resolve_saving_throw", side_effect=observe),
            patch("check_resolution.dice_roll", side_effect=[_d20(3), _d20(18)]) as dice,
        ):
            result = await break_concentration_on_damage(
                session,
                4,
                False,
                damaged_player_id=guest,
                **({"combat_state": working} if working_state else {}),
            )
            assert saved == [18] and dice.call_count == 2
        assert result is None
        await assert_concentration(world, True)


async def test_death_save_inside_hearth_is_straight(world: SimpleNamespace) -> None:
    async with hearth(world) as call:
        await light_hearth(world, call)
        guest = world.ids[1]
        await fall(world, 1)
        await checkpoint(world)
        with patch("combat_resolution.dice_roll", side_effect=[_d20(3), _d20(18)]) as dice:
            offer = (await call("request_death_save", player_id=guest))["fate_offer"]
            assert (offer["roller_id"], offer["die"]) == (guest, 3)
            result = await keep_original(world, call, offer)
            dice.assert_called_once()
        assert (result["roll"], result["success"], result["total_failures"]) == (3, False, 2)
        for state in (active(world), await reload_state(world)):
            fallen = participant(state, guest)
            assert (fallen.hp_current, fallen.is_fallen, fallen.death_save_failures) == (0, True, 2)
        assert (await row(world, 1))["hp"]["current"] == 0


async def test_fate_pause_keeps_final_round_zone_and_does_not_repeat_healing(world: SimpleNamespace) -> None:
    async with hearth(world) as call:
        await light_hearth(world, call)
        owner, guest = world.ids
        state = active(world)
        state.hearthfire_zones[0]["rounds_remaining"] = 1
        state.round_number = 3
        state.round_checkpoints = []  # the jump skips rounds, so earlier round-start checkpoints no longer chain
        participant(state, owner).conditions = apply_condition([], "frightened", source=FOE, duration=3)
        participant(state, FOE).conditions = apply_condition([], "frightened", source=owner, duration=3)
        await fall(world, 1)
        await checkpoint(world)
        await declare(world, call)
        await call("resolve_phase")
        before = len(events(world))

        with (
            healing_rolls(4, 6) as dice,
            patch("check_resolution.dice_roll", side_effect=[_d20(3), _d20(18), _d20(3), _d20(18)]) as save_die,
        ):
            paused = await call("resolve_phase")
            offer = paused["fate_offer"]
            assert offer["roller_id"] == owner and offer["eligible_followers"] == [guest]
            assert (offer["die"], save_die.call_count) == (18, 2)
            assert paused["next"]["verbs"] == ["activate"]
            assert paused["hearthfire"]["zones"][0]["rounds_remaining"] == 1
            receipts = paused["hearthfire"]["heals"]
            assert {r["target_id"]: r["healed"] for r in receipts} == {owner: 2, guest: 4, COMPANION: 4}
            saved = (await snapshot(world))[2]
            assert saved["wrap_continuation"]["wrap"]["hearthfire_heals"] == receipts
            assert saved["hearthfire_zones"][0]["rounds_remaining"] == 1
            for index, hp in enumerate((100, 4)):
                assert (
                    participant(active(world), world.ids[index]).hp_current
                    == (await row(world, index))["hp"]["current"]
                    == hp
                )
            hp_events = [e for e in events(world)[before:] if e["type"] == E.HP_CHANGED]
            assert [e["current"] for e in hp_events] == [100, 4]

            foe_pause = await keep_original(world, call, offer)
            foe_offer = foe_pause["fate_offer"]
            assert (foe_offer["roller_id"], foe_offer["die"], save_die.call_count) == (FOE, 3, 3)
            assert foe_pause["hearthfire"]["zones"][0]["rounds_remaining"] == 1
            assert (await snapshot(world))[2]["hearthfire_zones"][0]["rounds_remaining"] == 1
            result = await keep_original(world, call, foe_offer)
            dice.assert_called_once_with("1d6")
            assert save_die.call_count == 3

        assert world.ctx.userdata.fate_offer is None and active(world).wrap_continuation is None
        assert result["hearthfire"] == {"zones": [], "heals": receipts}
        assert result["death_saves_due"] == [] and result["next"]["phase"] == "declaration"
        assert result["round"] == 4
        assert [e for e in events(world)[before:] if e["type"] == E.HP_CHANGED] == hp_events
        active_live = active(world).to_dict()
        assert (await reload_state(world)).to_dict() == active_live
        assert active(world).hearthfire_zones == []
        revived = participant(active(world), guest)
        assert (revived.hp_current, revived.is_fallen, revived.death_save_failures, revived.death_save_successes) == (
            4,
            False,
            0,
            0,
        )
        assert (await row(world, 1))["hp"]["current"] == 4
        assert not has_condition(participant(active(world), owner).conditions, "frightened")
        assert has_condition(participant(active(world), FOE).conditions, "frightened")
