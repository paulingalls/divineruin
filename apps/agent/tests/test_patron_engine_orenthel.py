"""Restoration Surge through the registered activate and rest tools."""

from contextlib import asynccontextmanager
from copy import deepcopy

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import encounter, row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import game_tools
from acceptance._capstone_helpers import _enemy, _player
from acceptance.seeds import seed_player_with_pools
from acceptance.test_kaelen_iron_resolve_capstone import required_player
from livekit.agents.llm import ToolError
from sample_fixtures import published_payloads
from test_aelora_gift import _live_party

import conditions
import db_mutations
import db_queries
from activate_tools import activate
from db_mutations_conditions import save_player_conditions
from rest_tools import rest

SURGE = "orenthel_restoration_surge"
SPENT = {"spent": True}
OTHER_GIFTS = {"orenthel_dawns_embrace": SPENT}
CONDITIONS = ["poisoned", "blinded", "frightened", "hollowed"]
CASES = [
    (kind, combat, actor, target)
    for index, kind in enumerate(CONDITIONS)
    for combat, actor, target in [(False, 0, 1 - index % 2), (True, 1, index % 2)]
]


def afflicted(kind, stage=1):
    record = conditions.apply_condition([], kind, duration=3, source="trap")[0]
    if kind == "hollowed":
        record["stage"] = stage
    return record


def survivors(kind):
    other = "frightened" if kind == "poisoned" else "poisoned"
    return [afflicted(other), afflicted("exhausted") | {"stacks": 2}]


@asynccontextmanager
async def surge_setup(world, *, stored, combat=False, live=None, actor=0, target=1, spent=False, case=None):
    session = world.ctx.userdata
    session.location_id = "millhaven_inn"
    for index, pid in enumerate(world.ids):
        await seed_player_with_pools(world.pool, player_id=pid, class_="mage", focus_current=3 + index)
        await configure(
            world,
            "orenthel" if index == actor else "veythar",
            "mage",
            index=index,
            location_id=session.location_id,
            conditions=stored if index == target else [],
            patron_gifts=OTHER_GIFTS | ({SURGE: SPENT} if spent else {}) if index == actor else {},
        )
    lifecycle = _live_party(session, *(world.ids[:1] if case == "disconnected" else world.ids))
    state = None
    try:
        if combat:
            encounter(world)
            state = session.combat_state
            state.combat_id = world.ids[0]
            state.initiative_order = list(state.initiative_order)
            participant = required_player(state, world.ids[target])
            participant.conditions = deepcopy((stored or []) if live is None else live)
            if case in {"outside_combat", "actor_outside_combat"}:
                removed = world.ids[target if case == "outside_combat" else actor]
                state.participants.remove(required_player(state, removed))
                state.initiative_order.remove(removed)
            if case in {"enemy", "companion"}:
                extra = _enemy(case, hp=20)
                extra.type = case
                extra.conditions = deepcopy(participant.conditions)
                state.participants.append(extra)
                state.initiative_order.append(extra.id)
            await db_mutations.save_combat_state(state.combat_id, state.to_dict(), conn=world.pool)
        with session._bind_authenticated_actor(world.ids[actor], 1, lifecycle.require_authorized):
            yield game_tools(session, activate, rest)
    finally:
        await lifecycle.aclose()
        if state is not None:
            await db_mutations.delete_combat_state(state.combat_id, conn=world.pool)


async def checkpoint(world, *, conn=None):
    state = world.ctx.userdata.combat_state
    if state is None:
        return None
    saved = await db_mutations.load_combat_state(state.combat_id, conn=conn or world.pool)
    assert saved is not None
    return saved.to_dict()


async def snapshot(world):
    session = world.ctx.userdata
    return (
        [await row(world, index) for index in range(len(world.ids))],
        session.combat_state.to_dict() if session.in_combat else None,
        await checkpoint(world),
        published_payloads(session.room),
    )


async def restoration_scenario(world, kind, combat, actor, target):
    remaining = survivors(kind)
    live = [afflicted(kind), *remaining]
    stored = remaining if combat and kind == "blinded" else live
    async with surge_setup(world, stored=stored, combat=combat, live=live, actor=actor, target=target) as call:
        session = world.ctx.userdata
        original = session.combat_state
        before, original_checkpoint, _, _ = await snapshot(world)
        args = {"condition": kind}
        if actor != target:
            args["target_id"] = world.ids[target]
        result = await call("activate", id=SURGE, **args)
        assert result["target_id"] == world.ids[target]
        assert result["condition_removed"] == kind
        before[actor]["patron_gifts"][SURGE] = SPENT
        before[target]["conditions"] = remaining
        assert [await row(world, index) for index in range(len(world.ids))] == before
        if original is not None:
            assert original.to_dict() == original_checkpoint
            assert required_player(session.combat_state, world.ids[target]).conditions == remaining
            assert await checkpoint(world) == session.combat_state.to_dict()
        if (kind, combat) == ("poisoned", False):
            await verify_long_rest(world, call, args, actor, target)


async def verify_long_rest(world, call, args, actor, target):
    await save_player_conditions(world.ids[target], [afflicted("poisoned"), *survivors("poisoned")], conn=world.pool)
    before = await snapshot(world)
    with pytest.raises(ToolError, match=r"spent.*long rest"):
        await call("activate", id=SURGE, **args)
    assert await snapshot(world) == before
    await call("rest", rest_type="short")
    assert (await row(world, actor))["patron_gifts"][SURGE] == SPENT
    await call("rest", rest_type="long")
    refreshed = [await row(world, index) for index in range(len(world.ids))]
    assert not refreshed[actor]["patron_gifts"].get(SURGE, {}).get("spent")
    await call("activate", id=SURGE, **args)
    refreshed[actor]["patron_gifts"][SURGE] = SPENT
    refreshed[target]["conditions"] = survivors("poisoned")
    assert [await row(world, index) for index in range(len(world.ids))] == refreshed


async def assert_refused(world, call, reason, **args):
    before = await snapshot(world)
    with pytest.raises(ToolError, match=reason):
        await call("activate", **args)
    assert await snapshot(world) == before


@pytest.mark.parametrize("combat", [False, True], ids=["exploration", "combat"])
@pytest.mark.parametrize(
    "selected,reason",
    [
        (None, "requires a condition selector"),
        ("stunned", "cannot remove 'stunned'"),
        ("blinded", "does not have 'blinded'"),
    ],
)
async def test_condition_selector_refusals(world, combat, selected, reason):
    stored = [afflicted("poisoned"), afflicted("stunned")]
    if combat:
        stored.append(afflicted("blinded"))
    async with surge_setup(world, stored=stored, combat=combat, live=stored[:2]) as call:
        target = world.ids[1]
        await assert_refused(world, call, reason, id=SURGE, target_id=target, condition=selected)
        await call("activate", id=SURGE, target_id=target, condition="poisoned")


@pytest.mark.parametrize(
    "combat,stored_stage,live_stage", [(False, 2, 1), (False, 3, 1), (True, 2, 1), (True, 1, 2), (True, 3, 3)]
)
async def test_higher_hollowed_stages_are_preserved(world, combat, stored_stage, live_stage):
    poison = afflicted("poisoned")
    async with surge_setup(
        world,
        stored=[afflicted("hollowed", stored_stage), poison],
        combat=combat,
        live=[afflicted("hollowed", live_stage), poison],
    ) as call:
        target = world.ids[1]
        await assert_refused(world, call, "stage 1 Hollowed", id=SURGE, target_id=target, condition="hollowed")
        await call("activate", id=SURGE, target_id=target, condition="poisoned")


async def test_null_stored_conditions_are_absent_in_exploration(world):
    async with surge_setup(world, stored=None) as call:
        target = world.ids[1]
        await assert_refused(world, call, "does not have 'poisoned'", id=SURGE, target_id=target, condition="poisoned")
        await save_player_conditions(target, [afflicted("poisoned")], conn=world.pool)
        await call("activate", id=SURGE, target_id=target, condition="poisoned")


async def test_spent_surge_leaves_the_combat_condition_in_place(world):
    async with surge_setup(world, stored=[afflicted("poisoned")], combat=True, spent=True) as call:
        await assert_refused(world, call, r"spent.*long rest", id=SURGE, target_id=world.ids[1], condition="poisoned")


async def test_non_party_player_refused_without_writes(world):
    poison = afflicted("poisoned")
    async with surge_setup(world, stored=[poison]) as call:
        outsider = f"{world.ids[0]}_outsider"
        await seed_player_with_pools(world.pool, player_id=outsider, class_="mage")
        try:
            await save_player_conditions(outsider, [poison], conn=world.pool)
            before = await db_queries.get_player(outsider, conn=world.pool)
            await assert_refused(
                world, call, "present party member", id=SURGE, target_id=outsider, condition="poisoned"
            )
            assert await db_queries.get_player(outsider, conn=world.pool) == before
            await call("activate", id=SURGE, target_id=world.ids[1], condition="poisoned")
        finally:
            await world.pool.execute("DELETE FROM players WHERE player_id=$1", outsider)


@pytest.mark.parametrize(
    "case,combat,reason",
    [
        ("many", False, "targets one player"),
        ("enemy", True, "present party member"),
        ("companion", True, "present party member"),
        ("disconnected", False, "present party member"),
        ("outside_combat", True, "target to be a player participant"),
        ("actor_outside_combat", True, "acting player to be a player participant"),
    ],
)
async def test_ineligible_targets_refuse_without_writes(world, case, combat, reason):
    poison = afflicted("poisoned")
    async with surge_setup(world, stored=[poison], combat=combat, case=case) as call:
        actor, ally = world.ids
        if case == "many":
            target_args = {"target_id": ally, "target_ids": [actor, ally]}
        else:
            target_args = {"target_id": case if case in {"enemy", "companion"} else ally}
        await assert_refused(world, call, reason, id=SURGE, condition="poisoned", **target_args)
        if case == "actor_outside_combat":
            session = world.ctx.userdata
            session.combat_state.participants.append(_player(actor))
            session.combat_state.initiative_order.append(actor)
        if case in {"disconnected", "outside_combat"}:
            await save_player_conditions(actor, [poison], conn=world.pool)
            if combat:
                required_player(world.ctx.userdata.combat_state, actor).conditions = [poison]
            await call("activate", id=SURGE, condition="poisoned")
        else:
            await call("activate", id=SURGE, target_id=ally, condition="poisoned")


@pytest.mark.parametrize("ability", ["veythar_lorekeepers_library", "zhael_fates_thread"])
async def test_condition_selector_is_exclusive_to_surge(world, ability):
    async with surge_setup(world, stored=[afflicted("poisoned")]) as call:
        await configure(world, ability.split("_", 1)[0], "mage")
        await assert_refused(world, call, "selector is only for Restoration Surge", id=ability, condition="poisoned")
        if ability == "veythar_lorekeepers_library":
            await call("activate", id=ability)


SCENARIOS = {
    SURGE: ("patron_combat_edges:restoration_surge", restoration_scenario, CASES),
}
