from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from _aelora_hearthfire_fixtures import COMPANION, GIFT, hearth, move, point
from _mortaen_threshold_fixtures import FOE, SWORD, active, claw, declare, drain, rolls
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import world as world
from acceptance._capstone_helpers import _d20
from test_patron_engine_valdris import checkpoint, reload_state
from voice_condition_fixtures import participant

import architect_encounter
import check_resolution_attack
import check_resolution_save
import concentration_break
import db_mutations
import db_queries
from combat_opportunity import STRIKE
from combat_packet import _resolve_one_packet
from combat_phase import ResolutionPacket
from combat_spatial import require_spatial
from combat_structures import THORNWALL, add_wall
from conditions import apply_condition
from declarations import Declaration, DeclarationType
from patron_gift_tools import write_state
from zhael_fate import FATE


async def start_outside(
    world: SimpleNamespace, call: Any, *, x: float = 30, z: float = 0, suppress_fate: bool = True
) -> None:
    state = active(world)
    require_spatial(state)["positions"][FOE] = point(x, z)
    require_spatial(state)["speeds"][FOE] = 65
    if suppress_fate:
        await spend_fate(world)
    await checkpoint(world)
    await call("activate", id=GIFT)


async def spend_fate(world: SimpleNamespace) -> None:
    async with world.pool.acquire() as conn:
        await write_state(world.ids[1], {"spent": True}, gift_id=FATE, conn=conn)


@pytest.mark.parametrize("melee", [False, True], ids=["direct", "melee"])
async def test_entry_refusal(world: SimpleNamespace, melee: bool) -> None:
    async with hearth(world) as call:
        await start_outside(world, call)
        owner = world.ids[0]
        action = claw(world) if melee else move(FOE, -30)
        with rolls(2), patch("check_resolution.dice_roll", return_value=_d20(2)) as dice:
            await declare(world, call, action)
            dice.assert_not_called()
            state = await reload_state(world)
            assert require_spatial(state)["positions"][FOE] == point(30)
            assert state.hearthfire_zones[0]["failed_rounds"] == {}
            packets, _ = await drain(world, call)
            dice.assert_called_once()
        movement = next(packet for packet in packets if packet.get("actor_id") == FOE)
        state = await reload_state(world)
        assert require_spatial(state)["positions"][FOE]["x"] == pytest.approx(20)
        assert movement["moved_ft"] == pytest.approx(10)
        assert movement["movement_spent_ft"] == pytest.approx(10)
        assert movement["hearthfire_entries"][0]["success"] is False
        assert state.hearthfire_zones[0]["failed_rounds"] == {FOE: 1}
        if melee:
            assert movement["attack_resolved"] is False
            assert participant(state, owner).hp_current == 100


async def shipped_hearthfire(world: SimpleNamespace) -> None:
    async with hearth(world) as call:
        state = active(world)
        require_spatial(state)["positions"][FOE] = point(30)
        await checkpoint(world)
        gift = next(gift for gift in (await call("query_info", kind="patron"))["abilities"] if gift["id"] == GIFT)
        assert (gift["tier"], gift["status"], gift["state"], gift["recharge"], gift["available"]) == (
            "Exalted",
            "active",
            "ready",
            "per_session",
            True,
        )
        assert f'activate(id="{GIFT}")' in gift["activation_hint"]
        await spend_fate(world)
        await call("activate", id=gift["id"])
        with rolls(20), patch("check_resolution.dice_roll", return_value=_d20(20)) as dice:
            for x in (10, 30, 10):
                await declare(world, call, move(FOE, x))
                packets, _ = await drain(world, call)
                saved = await reload_state(world)
                assert require_spatial(saved)["positions"][FOE] == point(x)
                if saved.round_number == 2:
                    movement = next(packet for packet in packets if packet.get("actor_id") == FOE)
                    assert movement["hearthfire_entries"][0]["success"] is True
                    assert saved.hearthfire_zones[0]["admitted_ids"] == [FOE]
            dice.assert_called_once()
        refreshed = next(g for g in (await call("query_info", kind="patron"))["abilities"] if g["id"] == GIFT)
        assert refreshed["spent"] and not refreshed["available"]


SCENARIOS = {GIFT: ("aelora_hearthfire:place", shipped_hearthfire, [()])}


@pytest.mark.parametrize("melee", [False, True], ids=["direct", "held-melee"])
async def test_entry_save_pauses_for_fate_and_keeps_the_reroll(world: SimpleNamespace, melee: bool) -> None:
    async with hearth(world) as call:
        await start_outside(world, call, suppress_fate=False)
        await declare(world, call, claw(world) if melee else move(FOE, 10))
        await call("resolve_phase")
        faces = [2, 19, 17] if melee else [2, 19]
        with rolls(damage=1), patch("check_resolution.dice_roll", side_effect=map(_d20, faces)) as dice:
            offer = (await call("resolve_phase"))["fate_offer"]
            assert (offer["roller_id"], offer["die"]) == (FOE, 2)
            state = await reload_state(world)
            assert require_spatial(state)["positions"][FOE]["x"] == pytest.approx(20)
            assert state.hearthfire_zones[0]["failed_rounds"] == {}
            with world.ctx.userdata._bind_authenticated_actor(world.ids[1], 1, lambda *_: None):
                await call("activate", id=FATE, offer_id=offer["offer_id"])
                result = await call("activate", id=FATE, offer_id=offer["offer_id"], keep="reroll")
            assert dice.call_count == len(faces)
        movement = next(packet for packet in result["packets"] if packet.get("actor_id") == FOE)
        assert movement["hearthfire_entries"][0]["roll"] == 19
        state = await reload_state(world)
        assert require_spatial(state)["positions"][FOE] == point(15 if melee else 10)
        assert state.hearthfire_zones[0]["admitted_ids"] == [FOE]


@pytest.mark.parametrize("outcome", ["dropped", "refused", "admitted"])
async def test_earlier_opportunity_settles_before_entry(world: SimpleNamespace, outcome: str) -> None:
    async with hearth(world) as call:
        await start_outside(world, call)
        owner, guest = world.ids
        state = active(world)
        require_spatial(state)["positions"].update({owner: point(30), guest: point(20), COMPANION: point(0)})
        reach_weapon = {**SWORD, "name": "Pike", "type": "melee", "reach": 10}
        await configure(
            world,
            "zhael",
            "warrior",
            index=1,
            equipment={"main_hand": reach_weapon},
            patron_gifts={FATE: {"spent": True}},
        )
        later = participant(state, guest)
        later.action_pool = [reach_weapon]
        later.reaction_ids.append(STRIKE)
        later.has_reaction_ability = True
        participant(state, FOE).hp_current = 1 if outcome == "dropped" else 50
        await checkpoint(world)
        faces = [18] if outcome == "dropped" else [18, 16 if outcome == "admitted" else 2]
        with rolls(damage=8), patch("check_resolution.dice_roll", side_effect=map(_d20, faces)) as dice:
            await declare(world, call, {**claw(world, reach=5), "target_id": COMPANION})
            await call("resolve_phase")
            paused = await call("resolve_phase")
            waiting = paused["next"]["waiting_on"]
            assert waiting["stage"] == "movement"
            assert [reaction["actor_id"] for reaction in waiting["reactions"]] == [owner]
            saved = await reload_state(world)
            assert require_spatial(saved)["positions"][FOE] == point(25)
            assert saved.hearthfire_zones[0]["failed_rounds"] == {}
            dice.assert_not_called()
            with world.ctx.userdata._bind_authenticated_actor(owner, 1, lambda *_: None):
                await call("activate", id=STRIKE)
            resumed = await call("resolve_phase")
            assert dice.call_count == len(faces)
        state = await reload_state(world)
        strike = next(packet for packet in resumed["packets"] if packet.get("reaction") == STRIKE)
        assert strike["hit"] is True
        if outcome == "dropped":
            assert participant(state, FOE).is_fallen
            assert require_spatial(state)["positions"][FOE] == point(25)
            assert state.hearthfire_zones[0]["failed_rounds"] == {}
        elif outcome == "refused":
            assert require_spatial(state)["positions"][FOE]["x"] == pytest.approx(20)
            assert state.hearthfire_zones[0]["failed_rounds"] == {FOE: 1}
            assert resumed["next"].get("waiting_on") is None
        else:
            assert require_spatial(state)["positions"][FOE] == point(10)
            assert state.hearthfire_zones[0]["admitted_ids"] == [FOE]
            pending = next(packet for packet in resumed["packets"] if packet.get("attack_pending"))
            assert pending["moved_ft"] == 20 and pending["hearthfire_entries"][0]["roll"] == 16
            waiting = resumed["next"]["waiting_on"]
            assert waiting["stage"] == "movement"
            assert [reaction["actor_id"] for reaction in waiting["reactions"]] == [guest]


async def test_refused_multiattack_retries_once_next_round(world: SimpleNamespace) -> None:
    async with hearth(world) as call:
        await start_outside(world, call)
        state = active(world)
        owner, guest = world.ids
        require_spatial(state)["positions"][guest] = point(7)
        enemy = participant(state, FOE)
        enemy.multiattack_sequence = {"name": "Double Claw", "attacks": ["Claw", "Claw"]}
        await checkpoint(world)
        attack = {
            "kind": "multiattack",
            "actor_id": FOE,
            "action": "Double Claw",
            "strikes": [{"action": "Claw", "target_id": target, "held_item_id": ""} for target in (owner, guest)],
        }
        with rolls(), patch("check_resolution.dice_roll", return_value=_d20(2)) as dice:
            await declare(world, call, attack)
            packets, _ = await drain(world, call)
            movements = [packet for packet in packets if packet.get("actor_id") == FOE]
            assert len(movements) == 2 and all(not packet["attack_resolved"] for packet in movements)
            first, second = [packet["hearthfire_entries"][0] for packet in movements]
            assert first["roll"] == 2 and second["same_round"]
            dice.assert_called_once()
            await reload_state(world)
            await declare(world, call, move(FOE, 10))
            packets, _ = await drain(world, call)
            assert dice.call_count == 2
        state = await reload_state(world)
        assert state.hearthfire_zones[0]["failed_rounds"] == {FOE: 2}
        assert require_spatial(state)["positions"][FOE]["x"] == pytest.approx(20)


@pytest.mark.parametrize("limit", ["speed", "wall", "pit", "restrained"])
async def test_short_routes_never_reach_hearthfire(world: SimpleNamespace, limit: str) -> None:
    async with hearth(world) as call:
        await start_outside(world, call)
        state = active(world)
        if limit == "speed":
            require_spatial(state)["speeds"][FOE] = 5
        elif limit == "wall":
            add_wall(
                state, "thorns", "Thornwall", {"x": 24, "y": -5, "z": 0}, {"x": 24, "y": 5, "z": 0}, kind=THORNWALL
            )
        elif limit == "pit":
            architect = participant(state, "mawling_2")
            architect.creature_id = architect_encounter.CREATURE_ID
            architect_encounter.initialize(state)
            assert state.architect_encounter is not None
            state.architect_encounter["floors"]["f"] = {
                "min": {"x": 25, "y": -5, "z": 0},
                "max": {"x": 35, "y": 5, "z": 0},
            }
            state.architect_encounter["pits"][FOE] = "f"
        else:
            enemy = participant(state, FOE)
            enemy.conditions = apply_condition(enemy.conditions, "restrained")
        await checkpoint(world)
        with rolls(damage=1), patch("check_resolution.dice_roll") as dice:
            await call(
                "declare_phase",
                declarations=[
                    claw(world),
                    *(
                        {"kind": "defend", "actor_id": actor.id, "reshape": []}
                        for actor in state.participants
                        if actor.id != FOE and not actor.is_structure
                    ),
                ],
            )
            packets, _ = await drain(world, call)
            dice.assert_not_called()
        movement = next(packet for packet in packets if packet.get("actor_id") == FOE)
        assert movement["attack_resolved"] is False and "hearthfire_entries" not in movement
        state = await reload_state(world)
        assert require_spatial(state)["positions"][FOE]["x"] > 20
        if limit == "pit":
            assert state.architect_encounter is not None
            assert movement["left_pit"] and FOE not in state.architect_encounter["pits"]
        elif limit == "wall":
            assert movement["thornwall_id"] == "thorns"
        assert state.hearthfire_zones[0]["failed_rounds"] == {}
        assert state.hearthfire_zones[0]["admitted_ids"] == []


@pytest.mark.parametrize(("height", "face", "edge"), [(9, 13, 17), (9, 14, -30), (16, None, -30)])
async def test_swept_entry_uses_height_and_both_creatures_save_stats(
    world: SimpleNamespace, height: int, face: int | None, edge: int
) -> None:
    async with hearth(world) as call:
        await start_outside(world, call, z=height)
        state = active(world)
        follower = participant(state, world.ids[0])
        follower.level = 14
        follower.attributes["wisdom"] = 20
        participant(state, FOE).attributes["wisdom"] = 14
        await checkpoint(world)
        action = {**move(FOE, -30), "destination": point(-30, height)}
        with rolls(), patch("check_resolution.dice_roll", side_effect=[] if face is None else [_d20(face)]) as dice:
            await declare(world, call, action)
            packets, _ = await drain(world, call)
            assert dice.call_count == (0 if face is None else 1)
        movement = next(packet for packet in packets if packet.get("actor_id") == FOE)
        if face is None:
            assert "hearthfire_entries" not in movement
        else:
            receipt = movement["hearthfire_entries"][0]
            assert (receipt["dc"], receipt["roll"], receipt["total"], receipt["success"]) == (
                16,
                face,
                face + 2,
                face == 14,
            )
        saved = await reload_state(world)
        assert require_spatial(saved)["positions"][FOE] == pytest.approx(point(edge, height))


async def test_activation_occupant_saves_only_after_leaving(world: SimpleNamespace) -> None:
    async with hearth(world) as call:
        await spend_fate(world)
        state = active(world)
        require_spatial(state)["positions"][FOE] = point(10)
        await checkpoint(world)
        await call("activate", id=GIFT)
        with rolls(), patch("check_resolution.dice_roll", side_effect=[_d20(2)]) as dice:
            for x in (12, 30):
                await declare(world, call, move(FOE, x))
                await drain(world, call)
                dice.assert_not_called()
                state = await reload_state(world)
                assert require_spatial(state)["positions"][FOE] == point(x)
                assert state.hearthfire_zones[0]["admitted_ids"] == []
            await declare(world, call, move(FOE, 10))
            packets, _ = await drain(world, call)
            dice.assert_called_once()
        movement = next(packet for packet in packets if packet.get("actor_id") == FOE)
        assert movement["hearthfire_entries"][0]["success"] is False
        assert require_spatial(await reload_state(world))["positions"][FOE]["x"] == pytest.approx(20)


@pytest.mark.parametrize("ranged", [True, False])
async def test_attacks_that_need_no_entry_still_hit(world: SimpleNamespace, ranged: bool) -> None:
    async with hearth(world) as call:
        await start_outside(world, call, x=30 if ranged else 21)
        state = active(world)
        owner, guest = world.ids
        require_spatial(state)["positions"].update({owner: point(16), guest: point(24, 9)})
        await checkpoint(world)
        action = claw(world, type="ranged") if ranged else claw(world)
        with (
            rolls(damage=6),
            patch("check_resolution.dice_roll", return_value=_d20(17)),
            patch.object(
                check_resolution_save, "roll_participant_save", wraps=check_resolution_save.roll_participant_save
            ) as saves,
        ):
            await declare(world, call, action, move(guest, 5))
            packets, _ = await drain(world, call)
            saves.assert_not_called()
        attack = next(packet for packet in packets if packet.get("actor_id") == FOE)
        assert attack["hit"] is True and attack["damage"] > 0 and "hearthfire_entries" not in attack
        saved = await reload_state(world)
        assert require_spatial(saved)["positions"][FOE] == point(30 if ranged else 21)
        assert require_spatial(saved)["positions"][guest] == point(5)
        assert saved.hearthfire_zones[0]["admitted_ids"] == []
        assert saved.hearthfire_zones[0]["failed_rounds"] == {}


async def test_nonheld_packet_cannot_bypass_entry(world: SimpleNamespace) -> None:
    async with hearth(world) as call:
        await start_outside(world, call)
        state = active(world)
        owner = world.ids[0]
        hp = participant(state, owner).hp_current
        packet = ResolutionPacket(FOE, Declaration(DeclarationType.ATTACK, "Claw", target_id=owner), 0)
        async with world.pool.acquire() as conn:
            with patch("check_resolution.dice_roll", side_effect=[_d20(2)]) as dice:
                result = await _resolve_one_packet(
                    world.ctx.userdata,
                    state,
                    packet,
                    conn=conn,
                    mutations=db_mutations,
                    queries=db_queries,
                    resolver=check_resolution_attack,
                    concentration_break_mod=concentration_break,
                )
                dice.assert_called_once()
        assert result["attack_resolved"] is False
        assert result["hearthfire_entries"][0]["success"] is False
        assert participant(state, owner).hp_current == hp
