from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from unittest.mock import call as mock_call

import pytest
from _aelora_hearthfire_fixtures import (
    COMPANION,
    GIFT,
    OTHER_GIFTS,
    fall,
    healing_rolls,
    hearth,
    move,
    point,
    refuse,
    snapshot,
)
from _mortaen_threshold_fixtures import FOE, active, declare, drain, events
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import game_tools
from acceptance._capstone_helpers import _d20
from asyncpg import Connection
from test_patron_engine_valdris import checkpoint, reload_state
from voice_condition_fixtures import participant

import db_mutations
import event_types as E
from conditions import apply_condition
from exploration_agent import ExplorationAgent
from zhael_fate import FATE, FateOffer, Resumed


async def test_places_fixed_sphere_spends_and_reports_occupants(world: SimpleNamespace) -> None:
    async with hearth(world) as call:
        owner, guest = world.ids
        active(world).spatial["positions"][COMPANION] = point(5, 15.01)
        await checkpoint(world)
        before = await row(world, 0)

        result = await call("activate", id=GIFT)
        assert result["id"] == GIFT and result["recharge"] == "per_session"
        assert "Rook" in result["dm_cue"] and "Iris" in result["dm_cue"]
        zone = {
            "source_id": owner,
            "center": point(5),
            "radius_ft": 15,
            "rounds_remaining": 3,
            "admitted_ids": [],
            "failed_rounds": {},
        }
        occupants = [{"id": p.id, "name": p.name} for p in active(world).participants if p.id in {owner, guest, FOE}]
        facts = {
            "zones": [{**zone, "occupants": occupants}],
            "heals": [],
        }
        assert result["hearthfire"] == facts
        assert (await row(world, 0)) == {**before, "patron_gifts": {**OTHER_GIFTS, GIFT: {"spent": True}}}
        assert active(world).hearthfire_zones == (await reload_state(world)).hearthfire_zones == [zone]
        await refuse(world, call, "Already spent; requires a new session")

        await declare(world, call)
        ally_pass = await call("resolve_phase")
        assert ally_pass["round"] == 1 and ally_pass["next"]["phase"] == "narration"
        assert ally_pass["hearthfire"] == facts
        assert [(await row(world, index))["hp"]["current"] for index in (0, 1)] == [98, 30]

        state = active(world)
        legacy = state.to_dict()
        del legacy["hearthfire_zones"]
        await db_mutations.save_combat_state(state.combat_id, legacy, conn=world.pool)
        assert (await reload_state(world)).hearthfire_zones == []


async def test_round_heals_once_to_cap_and_tracks_current_occupants_until_expiry(world: SimpleNamespace) -> None:
    async with hearth(world) as call:
        owner, guest = world.ids
        active(world).spatial["positions"][guest] = point(10)
        await checkpoint(world)
        zone = (await call("activate", id=GIFT))["hearthfire"]["zones"][0]
        await fall(world, 1)
        await checkpoint(world)
        await declare(world, call)
        ally_pass = await call("resolve_phase")
        assert ally_pass["hearthfire"]["heals"] == []
        assert guest in {p["id"] for p in ally_pass["hearthfire"]["zones"][0]["occupants"]}
        assert (await row(world, 1))["hp"]["current"] == 0

        with healing_rolls(4, 2, 5, 6) as dice:
            _, first = await drain(world, call)
            assert isinstance(first, dict)
            assert first["death_saves_due"] == []
            found = {heal["target_id"]: heal for heal in first["hearthfire"]["heals"]}
            assert set(found) == {owner, guest, COMPANION}
            assert {pid: (r["rolled"], r["healed"], r["hp_current"], r["rose"]) for pid, r in found.items()} == {
                owner: (4, 2, 100, False),
                guest: (4, 4, 4, True),
                COMPANION: (4, 4, 14, False),
            }
            assert found[guest] == {
                "source_id": owner,
                "target_id": guest,
                "target_name": "Iris",
                "round": 1,
                "rolled": 4,
                "healed": 4,
                "hp_current": 4,
                "hp_max": 100,
                "rose": True,
            }
            assert active(world).hearthfire_zones == [
                {key: value for key, value in (zone | {"rounds_remaining": 2}).items() if key != "occupants"}
            ]
            revived = participant(active(world), guest)
            assert (revived.is_fallen, revived.death_save_successes, revived.death_save_failures) == (False, 0, 0)

            for number, actions in ((2, (move(owner, 16), move(guest, 24))), (3, (move(owner, 25),)), (4, ())):
                before = len(events(world))
                await declare(world, call, *actions)
                _, result = await drain(world, call)
                assert isinstance(result, dict)
                assert result["round"] == number + 1
                if number == 2:
                    facts = result["hearthfire"]["zones"][0]
                    assert facts["center"] == point(5) and facts["rounds_remaining"] == 1
                    assert {p["id"] for p in facts["occupants"]} == {owner, FOE, COMPANION}
                    assert active(world).hearthfire_zones == [{k: v for k, v in facts.items() if k != "occupants"}]
                    heals = result["hearthfire"]["heals"]
                    assert {r["target_id"]: r["healed"] for r in heals} == {owner: 0, COMPANION: 2}
                    assert all(r["round"] == 2 for r in heals)
                    assert E.HP_CHANGED not in {e["type"] for e in events(world)[before:]}
                else:
                    assert active(world).hearthfire_zones == []
                if number == 3:
                    assert result["hearthfire"]["zones"] == []
                    heals = result["hearthfire"]["heals"]
                    assert [(r["target_id"], r["round"], r["healed"]) for r in heals] == [(COMPANION, 3, 5)]

        assert dice.call_args_list == [mock_call("1d6")] * 3
        for index, expected in enumerate((100, 4)):
            assert (
                participant(active(world), world.ids[index]).hp_current
                == (await row(world, index))["hp"]["current"]
                == expected
            )
        assert participant(active(world), COMPANION).hp_current == 21
        assert participant(active(world), FOE).hp_current == 1


async def test_wrap_raises_every_recoverable_fallen_ally_before_death_saves(world: SimpleNamespace) -> None:
    async with hearth(world) as call:
        await call("activate", id=GIFT)
        await fall(world, 0, failures=3)
        await fall(world, 1)
        companion = participant(active(world), COMPANION)
        companion.is_fallen, companion.hp_current = True, 0
        active(world).beat = "narration"
        await checkpoint(world)
        with healing_rolls(3):
            result = await call("resolve_phase")
        assert result["next"]["phase"] == "declaration" and result["round"] == 2
        assert result["death_saves_due"] == []
        assert E.COMBAT_ENDED not in {event["type"] for event in events(world)}
        await reload_state(world)
        dead = participant(active(world), world.ids[0])
        assert (dead.hp_current, dead.is_fallen, dead.is_dead, dead.death_save_failures) == (0, True, False, 3)
        assert (await row(world, 0))["hp"]["current"] == 0
        assert (await row(world, 1))["hp"]["current"] == 3
        for pid in (world.ids[1], COMPANION):
            risen = participant(active(world), pid)
            assert (risen.hp_current, risen.is_fallen, risen.death_save_successes, risen.death_save_failures) == (
                3,
                False,
                0,
                0,
            )
        assert {r["target_id"] for r in result["hearthfire"]["heals"] if r["rose"]} == {world.ids[1], COMPANION}


async def test_ending_wrap_includes_heal_in_handoff(world: SimpleNamespace) -> None:
    async with hearth(world) as call:
        await call("activate", id=GIFT)
        state = active(world)
        for foe in (p for p in state.participants if p.type == "enemy"):
            foe.hp_current, foe.is_fallen = 0, True
        state.beat = "narration"
        await checkpoint(world)
        with healing_rolls(4):
            agent, result = await call("resolve_phase")
        assert isinstance(agent, ExplorationAgent) and result["outcome"] == "victory"
        assert result["hearthfire"]["zones"] == []
        assert {r["target_id"]: r["healed"] for r in result["hearthfire"]["heals"]}[world.ids[1]] == 4
        assert (await row(world, 1))["hp"]["current"] == 34
        assert active(world) is None
        assert await db_mutations.load_combat_state(state.combat_id, conn=world.pool) is None


async def test_wrap_healing_rolls_back_after_first_hp_write_and_retries(world: SimpleNamespace) -> None:
    async with hearth(world) as call:
        await call("activate", id=GIFT)
        await declare(world, call)
        await call("resolve_phase")
        before = await snapshot(world)
        write = db_mutations.update_player_hp

        async def fail_after_write(pid: str, hp: int, *, conn: Connection) -> None:
            if pid == world.ids[0]:
                await write(pid, hp, conn=conn)
                return
            assert (pid, hp) == (world.ids[1], 34)
            assert (
                await conn.fetchval(
                    "SELECT (data->'hp'->>'current')::int FROM players WHERE player_id=$1", world.ids[0]
                )
                == 100
            )
            raise RuntimeError("injected after hearth HP write")

        with healing_rolls(4, 4) as dice:
            with patch.object(db_mutations, "update_player_hp", side_effect=fail_after_write):
                with pytest.raises(RuntimeError, match="injected after hearth HP write"):
                    await call("resolve_phase")
            assert await snapshot(world) == before
            _, result = await drain(world, call)
            assert isinstance(result, dict)
        assert dice.call_args_list == [mock_call("1d6")] * 2
        assert result["hearthfire"]["zones"][0]["rounds_remaining"] == 2
        assert (await row(world, 1))["hp"]["current"] == 34
        assert [ev["current"] for ev in events(world)[len(before[3]) :] if ev["type"] == E.HP_CHANGED] == [100, 34]


async def test_queued_resolution_allows_activation_but_held_actions_refuse_it(world: SimpleNamespace) -> None:
    async with hearth(world) as call:
        await declare(world, call)
        queued = active(world).pending_declarations
        await call("resolve_phase")
        assert active(world).held_actions
        await refuse(world, call, "Finish the partially resolved round before using Hearthfire")

        await drain(world, call)
        await declare(world, call)
        resources = await row(world, 0)
        await call("activate", id=GIFT)
        assert active(world).beat == "resolution" and active(world).pending_declarations == queued
        assert await row(world, 0) == {**resources, "patron_gifts": {**OTHER_GIFTS, GIFT: {"spent": True}}}


async def test_live_fate_offer_refuses_activation_without_settling(world: SimpleNamespace) -> None:
    async with hearth(world) as call:
        owner, guest = world.ids
        session = world.ctx.userdata
        original = AsyncMock(return_value=Resumed({"outcome": "original"}))
        offer = FateOffer("live-save", "save", owner, 12, 12, {FATE: (guest,)}, Mock(), original, Mock())
        assert active(world).ally_continuation is None and not active(world).held_actions
        session.fate_offer = offer
        await refuse(world, call, "Finish the partially resolved round before using Hearthfire")
        assert session.fate_offer is offer
        original.assert_not_called()


async def test_paused_wrap_refuses_activation_after_its_offer_is_gone(world: SimpleNamespace) -> None:
    # A reload keeps the persisted wrap cursor but drops the in-memory Fate offer.
    async with hearth(world) as call:
        owner = world.ids[0]
        state = active(world)
        state.round_number = 3
        participant(state, owner).conditions = apply_condition([], "frightened", source=FOE, duration=3)
        await checkpoint(world)
        await declare(world, call)
        await call("resolve_phase")
        with patch("check_resolution.dice_roll", return_value=_d20(18)):
            assert (await call("resolve_phase"))["fate_offer"]
        world.ctx.userdata.fate_offer = None
        assert active(world).wrap_continuation is not None
        await refuse(world, call, "Finish the partially resolved round before using Hearthfire")


async def test_hearthfire_requires_a_standing_player_in_combat(world: SimpleNamespace) -> None:
    async with hearth(world) as call:
        session = world.ctx.userdata
        state = session.combat_state
        session.combat_state = None
        explore = game_tools(session, agent=ExplorationAgent())
        try:
            await refuse(world, explore, "Hearthfire can only be used in combat")
        finally:
            session.combat_state = state
        await fall(world, 0)
        await checkpoint(world)
        await refuse(world, call, "Hearthfire requires a standing player in this fight")


@pytest.mark.parametrize(
    ("patron", "favor", "reason"),
    [
        ("aelora", 40, "Requires Exalted tier"),
        ("valdris", 75, "This ability requires a follower of aelora"),
    ],
)
async def test_hearthfire_requires_exalted_aelora_favor(
    world: SimpleNamespace, patron: str, favor: int, reason: str
) -> None:
    async with hearth(world, patron=patron, favor=favor) as call:
        await refuse(world, call, reason)
