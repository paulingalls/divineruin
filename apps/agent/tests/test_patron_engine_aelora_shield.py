"""Community Shield through the registered activate, query and rest tools."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from _aelora_shield_fixtures import (
    NAMES,
    OTHER_GIFTS,
    SHIELD,
    SPENT,
    ToolCall,
    save_checkpoint,
    shield_setup,
    shield_status,
    snapshot,
)
from _thyra_wrath_fixtures import add_foe, fighter
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from livekit.agents.llm import ToolError

import combat_hold
import event_types as E
from session_data import CompanionState
from zhael_fate import FATE, FateOffer, Resumed


async def shield_scenario(
    world: SimpleNamespace, combat: bool, pool: int, level: int, charisma: int, queued: bool, amount: int
) -> None:
    async with shield_setup(world, combat=combat, pool=pool, level=level, charisma=charisma, queued=queued) as call:
        actor, ally = world.ids
        session = world.ctx.userdata
        original_state = session.combat_state
        rows, live, saved, _ = await snapshot(world)
        publish = session.room.local_participant.publish_data
        observed_health = []

        async def observe(data: bytes, **kwargs: object) -> None:
            if json.loads(data)["type"] == E.HP_CHANGED:
                observed_health.append(
                    ((await row(world, 1))["temp_hp"], (await row(world, 0))["patron_gifts"][SHIELD])
                )

        if not combat:
            publish.side_effect = observe
        gift = await shield_status(call)
        receipt = await call("activate", id=gift["id"], target_id=ally)
        assert (gift["tier"], gift["status"], gift["recharge"], gift["state"]) == (
            "Devoted",
            "active",
            "long_rest",
            "ready",
        )
        assert f'activate(id="{SHIELD}", target_id=' in gift["activation_hint"]
        assert (receipt["follower_id"], receipt["follower_name"]) == (actor, NAMES[0])
        assert (receipt["target_id"], receipt["target_name"]) == (ally, NAMES[1])
        assert (receipt["granted"], receipt["temp_hp"]) == (amount, amount)
        assert all(word in receipt["dm_cue"] for word in (*NAMES, str(amount)))
        after_rows, after_live, after_saved, _ = await snapshot(world)
        if original_state is not None:
            assert original_state.to_dict() == live
        assert rows[0] is not None and rows[1] is not None
        rows[0]["patron_gifts"][SHIELD] = SPENT
        rows[1]["temp_hp"] = amount
        assert after_rows == rows
        for original, updated in [(live, after_live), (saved, after_saved)]:
            if original is not None:
                next(p for p in original["participants"] if p["id"] == ally)["temp_hp"] = amount
            assert original == updated
        events = [
            (json.loads(args[0]), kwargs.get("destination_identities")) for args, kwargs in publish.call_args_list
        ]
        assert [
            (event["player_id"], recipients, shield["state"])
            for event, recipients in events
            if event["type"] == E.PATRON_ABILITIES_UPDATED
            for shield in event["abilities"]
            if shield["id"] == SHIELD
        ] == [(actor, [actor], "spent")]
        if combat:
            assert [
                player["tempHp"]
                for event, _ in events
                if event["type"] == E.COMBAT_UI_UPDATE
                for player in event["combatants"]
                if player["id"] == ally
            ] == [amount]
        else:
            assert [(event, recipients) for event, recipients in events if event["type"] == E.HP_CHANGED] == [
                ({"type": E.HP_CHANGED, "current": 18, "max": 20, "temp_hp": amount}, [ally])
            ]
            assert observed_health == [(amount, SPENT)]
            publish.side_effect = None
        refreshed = await shield_status(call)
        assert (refreshed["available"], refreshed["spent"], refreshed["state"]) == (False, True, "spent")
        if not combat:
            await recharge(world, call, ally)


async def recharge(world: SimpleNamespace, call: ToolCall, ally: str) -> None:
    await call("rest", rest_type="short", use_song_of_rest=False)
    assert (await shield_status(call))["state"] == "spent"
    await refuse(world, call, "spent.*long rest", ally)
    await call("rest", rest_type="long", use_song_of_rest=False)
    assert (await shield_status(call))["state"] == "ready"
    assert (await row(world, 1))["temp_hp"] == 0
    assert (await row(world, 0))["patron_gifts"] == {**OTHER_GIFTS, SHIELD: {"spent": False}}
    assert (await call("activate", id=SHIELD, target_id=ally))["temp_hp"] == 9
    assert (await row(world, 1))["temp_hp"] == 9
    assert (await shield_status(call))["state"] == "spent"


SCENARIOS = {
    SHIELD: (
        "patron_combat_edges:community_shield",
        shield_scenario,
        [
            (True, 0, 6, 16, False, 9),
            (False, 0, 6, 16, False, 9),
            (True, 4, 8, 14, True, 10),
            (True, 0, 1, 6, False, 1),
        ],
    )
}


async def refuse(world: SimpleNamespace, call: ToolCall, reason: str, target: str | None) -> None:
    before = await snapshot(world)
    with pytest.raises(ToolError, match=reason):
        await call("activate", id=SHIELD, **({} if target is None else {"target_id": target}))
    assert await snapshot(world) == before


@pytest.mark.parametrize(("combat", "pool"), [(True, 12), (False, 9)], ids=["larger", "equal"])
async def test_existing_pool_refuses_unspent(world: SimpleNamespace, combat: bool, pool: int) -> None:
    async with shield_setup(world, combat=combat, pool=pool) as call:
        await refuse(world, call, "would not increase", world.ids[1])


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("missing", "requires a target_id"),
        ("self", "targets another player"),
        ("companion", "present party player"),
        ("nonmember", "present party player"),
        ("departed", "present party player"),
        ("no_row", "not found"),
    ],
)
async def test_invalid_party_target(world: SimpleNamespace, case: str, reason: str) -> None:
    async with shield_setup(world, case=case) as call:
        actor, ally = world.ids
        if case == "companion":
            world.ctx.userdata.companion = CompanionState("companion", "Rowan")
        if case == "no_row":
            await world.pool.execute("DELETE FROM players WHERE player_id = $1", ally)
        targets = {"missing": None, "self": actor, "companion": "companion", "nonmember": "stranger"}
        await refuse(world, call, reason, targets.get(case, ally))


@pytest.mark.parametrize(
    ("index", "change", "reason"),
    [
        pytest.param(1, None, "target to be a player", id="absent-target"),
        pytest.param(1, {"type": "temporary_hollowed"}, "target to be a player", id="echo-target"),
        pytest.param(1, {"is_fallen": True}, "target to be standing", id="fallen-target"),
        pytest.param(1, {"is_dead": True}, "target to be standing", id="dead-target"),
        pytest.param(1, {"death_save_failures": 3}, "target to be standing", id="failed-saves"),
        pytest.param(0, None, "follower to be a player", id="absent-follower"),
        pytest.param(0, {"type": "temporary_hollowed"}, "follower to be a player", id="echo-follower"),
        pytest.param(0, {"is_fallen": True}, "follower to be standing", id="fallen-follower"),
        pytest.param(0, {"is_dead": True}, "follower to be standing", id="dead-follower"),
    ],
)
async def test_invalid_combat_participant(
    world: SimpleNamespace, index: int, change: dict[str, object] | None, reason: str
) -> None:
    async with shield_setup(world, combat=True) as call:
        state = world.ctx.userdata.combat_state
        participant = state.participants[index]
        if change is None:
            state.participants.remove(participant)
            state.initiative_order.remove(participant.id)
            del state.spatial["positions"][participant.id]
            del state.spatial["speeds"][participant.id]
        else:
            for field, value in change.items():
                setattr(participant, field, value)
        await save_checkpoint(world)
        await refuse(world, call, reason, world.ids[1])


@pytest.mark.parametrize(
    ("patron", "favor", "reason"), [("valdris", 40, "follower of aelora"), ("aelora", 39, "Devoted")]
)
async def test_ineligible_follower(world: SimpleNamespace, patron: str, favor: int, reason: str) -> None:
    async with shield_setup(world, patron=patron, favor=favor) as call:
        if patron == "aelora":
            assert (await shield_status(call))["state"] == "locked"
        await refuse(world, call, reason, world.ids[1])


async def test_held_round_refuses_unspent(world: SimpleNamespace) -> None:
    async with shield_setup(world, combat=True) as call:
        actor, ally = world.ids
        state = world.ctx.userdata.combat_state
        foe = fighter("foe")
        foe.action_pool = [{"name": "Claw", "damage": "1d4", "damage_type": "slashing", "properties": []}]
        add_foe(state, foe)
        state.pending_declarations = {foe.id: {"type": "attack", "action": "Claw", "target_id": actor}}
        state.held_actions = combat_hold.hold_enemy_packets(state, [SimpleNamespace(actor_id=foe.id, initiative=5)])
        assert state.held_actions
        await save_checkpoint(world)
        await refuse(world, call, "partially resolved", ally)


async def test_live_fate_offer_stays_open(world: SimpleNamespace) -> None:
    async with shield_setup(world, combat=True) as call:
        actor, ally = world.ids
        session = world.ctx.userdata
        original = AsyncMock(return_value=Resumed({"outcome": "original"}))
        offer = FateOffer("wrap-save", "save", actor, 12, 12, {FATE: (ally,)}, Mock(), original, Mock())
        session.fate_offer = offer
        await refuse(world, call, "partially resolved", ally)
        assert session.fate_offer is offer
        original.assert_not_called()
