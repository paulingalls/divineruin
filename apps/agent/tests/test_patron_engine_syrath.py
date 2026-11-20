from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import cast, encounter, phase, row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import defend, game_tools
from livekit.agents.llm import ToolError
from test_aelora_gift import _live_party

import combat_fate
import combat_phase
import db_mutations
from activate_tools import activate
from combat_participant import CombatParticipant
from combat_turn import declare_phase, resolve_phase
from conditions import apply_condition
from query_tools import query_info

VEILSTEP = "syrath_veilstep"
START = {"x": 5, "y": -10, "z": 2}
DESTINATION = {"x": 25, "y": 30, "z": 42}
OTHER_GIFTS = {"syrath_whisper_network": {"spent": True}}


async def hidden_casting_composes_and_persists(world, archetype, hidden, expected):
    w = world
    await configure(w, "syrath", archetype, flags={"concealed": hidden})
    packet = await cast(w, sid="arcane_fireball")
    assert packet["resonance_generated"] == expected
    assert (await row(w, 0))["resonance"]["current"] == (9 if expected == 0 else 7 + expected)
    assert w.ctx.userdata.party.primary.resonance.current == (9 if expected == 0 else 7 + expected)


async def test_hidden_guest_declared_cast(world):
    w = world
    await configure(w, "syrath", "seeker", index=1, flags={"concealed": True})
    encounter(w)
    with w.ctx.userdata._bind_authenticated_actor(w.ids[1], 4, lambda *_: None):
        packet = await phase(w)
    assert packet["packets"]
    assert (await row(w))["resonance"]["current"] == 9
    assert (await row(w, 0))["resonance"]["current"] == 9


@pytest.mark.parametrize("ward,corruption,expected", [(False, 0, 1), (True, 1, 0)])
async def test_hidden_casting_positive_generation(world, ward, corruption, expected):
    w = world
    await configure(w, "syrath", "mage", level=20, flags={"concealed": True})
    w.ctx.userdata.party.primary.corruption_level = corruption
    packet = await cast(w, sid="arcane_wall_of_force", ward=ward)
    assert packet["resonance_generated"] == expected
    assert (await row(w, 0))["resonance"]["current"] == (8 if expected else 9)


@asynccontextmanager
async def veilstep_scene(w: SimpleNamespace, *, geometry: str = "spatial", favor: int = 40):
    await configure(
        w,
        "syrath",
        "seeker",
        stamina={"current": 5, "max": 10},
        patron_gifts=OTHER_GIFTS,
        divine_favor={"patron": "syrath", "level": favor, "max": 100},
    )
    session = w.ctx.userdata
    _live_party(session, w.ids[1])
    if geometry != "none":
        actors = [*w.ids, "foe"]
        encounter(w)
        state = session.combat_state
        state.combat_id = w.ids[0]
        state.participants.append(CombatParticipant("foe", "Foe", "enemy", 5, 20, 20, 12))
        state.initiative_order = actors
        if geometry == "spatial":
            state.spatial = {
                "positions": {w.ids[0]: dict(START), w.ids[1]: {**START, "x": 40}, "foe": {**START, "x": 70}},
                "speeds": dict.fromkeys(actors, 30),
                "locations": {"arch": DESTINATION},
                "zones": {"arch_shadow": {"center_id": "arch", "radius_ft": 5}},
            }
        await db_mutations.save_combat_state(state.combat_id, state.to_dict(), conn=w.pool)
    try:
        yield game_tools(session, activate, query_info, declare_phase, resolve_phase)
    finally:
        if geometry != "none":
            await db_mutations.delete_combat_state(w.ids[0], conn=w.pool)


async def checkpoint(w: SimpleNamespace) -> dict | None:
    state = await db_mutations.load_combat_state(w.ids[0], conn=w.pool)
    return state.to_dict() if state else None


async def snapshot(w: SimpleNamespace) -> tuple:
    state = w.ctx.userdata.combat_state
    return (
        await row(w, 0),
        await checkpoint(w),
        state.to_dict() if state else None,
        w.ctx.userdata.room.local_participant.publish_data.await_count,
    )


async def step(w: SimpleNamespace, call, *, ability_id: str = VEILSTEP, **kwargs) -> dict:
    before = await row(w, 0)
    result = await call("activate", id=ability_id, **kwargs)
    before["patron_gifts"] = {**before["patron_gifts"], VEILSTEP: {"spent": True}}
    assert await row(w, 0) == before
    assert "shadow" in result["dm_cue"]
    return result


def move(actor: str, destination: dict) -> dict:
    return {"kind": "move", "actor_id": actor, "destination": destination}


async def veilstep_full_move(w: SimpleNamespace) -> None:
    async with veilstep_scene(w) as call:
        abilities = (await call("query_info", kind="patron"))["abilities"]
        gift = next(a for a in abilities if a["name"] == "Veilstep")
        assert (gift["id"], gift["tier"], gift["status"], gift["recharge"]) == (
            VEILSTEP,
            "Devoted",
            "active",
            "long_rest",
        )
        assert gift["available"] and not gift["spent"]
        assert f'activate(id="{VEILSTEP}", destination={{x,y,z}})' in gift["activation_hint"]
        assert "60 feet" in gift["activation_hint"]
        before = await checkpoint(w)
        assert before is not None
        result = await step(w, call, ability_id=gift["id"], destination=DESTINATION)
        assert result["position"] == DESTINATION
        before["spatial"]["positions"][w.ids[0]] = DESTINATION
        assert await checkpoint(w) == before == w.ctx.userdata.combat_state.to_dict()

        final = {**DESTINATION, "x": 55}
        with pytest.raises(ToolError, match="exceeds speed 30"):
            await call("declare_phase", declarations=[move(w.ids[0], {**final, "x": 56})])
        await call("declare_phase", declarations=[move(w.ids[0], final)])
        resolved = await call("resolve_phase")
        packet = next(p for p in resolved["packets"] if p["actor_id"] == w.ids[0])
        assert packet["resolved"] and packet["moved_ft"] == 30
        saved = await checkpoint(w)
        assert saved and saved["spatial"]["positions"][w.ids[0]] == final

        unchanged = await snapshot(w)
        with pytest.raises(ToolError, match=r"Already spent.*long rest"):
            await call("activate", id=VEILSTEP, destination=DESTINATION)
        assert await snapshot(w) == unchanged


async def test_veilstep_refuses_invalid_destinations_and_selectors(world: SimpleNamespace) -> None:
    async with veilstep_scene(world) as call:
        abilities = (await call("query_info", kind="patron"))["abilities"]
        assert next(a for a in abilities if a["id"] == VEILSTEP)["available"]
        start = await snapshot(world)
        for args, reason in (
            ({"destination": {"x": 5, "y": 1, "z": 62}}, "60 feet"),
            ({}, "requires a destination"),
            ({"target_id": world.ids[1]}, "takes a destination"),
            ({"target_ids": [world.ids[1]]}, "takes a destination"),
            ({"id": "zhael_fates_thread", "destination": DESTINATION}, "only for Veilstep"),
        ):
            with pytest.raises(ToolError, match=reason):
                await call("activate", **({"id": VEILSTEP} | args))
            assert await snapshot(world) == start
        assert (await step(world, call, destination=DESTINATION))["position"] == DESTINATION


@pytest.mark.parametrize("queued_move", [True, False])
async def test_veilstep_preserves_other_declarations(world: SimpleNamespace, queued_move: bool) -> None:
    async with veilstep_scene(world) as call:
        actor, ally = world.ids
        own = move(actor, {**START, "x": -25}) if queued_move else defend(actor)
        await call("declare_phase", declarations=[own, move(ally, {**START, "x": 45})])
        before = await checkpoint(world)
        assert before is not None and before["beat"] == "resolution"
        result = await step(world, call, destination=DESTINATION)
        if queued_move:
            del before["pending_declarations"][actor]
            assert "new move from the new position at the next declaration beat" in result["dm_cue"]
        before["spatial"]["positions"][actor] = DESTINATION
        assert await checkpoint(world) == before == world.ctx.userdata.combat_state.to_dict()
        packets = (await call("resolve_phase"))["packets"]
        assert any(p["actor_id"] == ally and p["moved_ft"] == 5 for p in packets)
        assert not any(p["actor_id"] == actor and "moved_ft" in p for p in packets)
        await call("resolve_phase")
        after = await checkpoint(world)
        assert after is not None and after["round_number"] == before["round_number"] + 1
        assert after["spatial"]["positions"][actor] == DESTINATION


@pytest.mark.parametrize("condition", ["restrained", "stunned"])
async def test_veilstep_through_movement_restrictions(world: SimpleNamespace, condition: str) -> None:
    async with veilstep_scene(world) as call:
        state = world.ctx.userdata.combat_state
        actor = state.get_participant(world.ids[0])
        actor.conditions = apply_condition([], condition)
        expected = state.to_dict()
        await db_mutations.save_combat_state(state.combat_id, expected, conn=world.pool)
        expected["spatial"]["positions"][actor.id] = DESTINATION
        assert (await step(world, call, destination=DESTINATION))["position"] == DESTINATION
        assert await checkpoint(world) == expected


@pytest.mark.parametrize(
    "geometry,flag,reason",
    [
        ("spatial", "favor", "Requires Devoted"),
        ("spatial", "is_fallen", "fallen or dead"),
        ("spatial", "is_dead", "fallen or dead"),
        ("legacy", "is_fallen", "fallen or dead"),
        ("spatial", "ally_continuation", "partially resolved"),
    ],
)
async def test_veilstep_refuses_ineligible_or_partly_resolved(
    world: SimpleNamespace, geometry: str, flag: str, reason: str
) -> None:
    async with veilstep_scene(world, geometry=geometry, favor=39 if flag == "favor" else 40) as call:
        state = world.ctx.userdata.combat_state
        actor = state.get_participant(world.ids[0])
        if flag.startswith("is_"):
            setattr(actor, flag, True)
        elif flag == "ally_continuation":
            await call("declare_phase", declarations=[move(actor.id, {**START, "x": -25})])
            state = world.ctx.userdata.combat_state
            resolving, advance = combat_phase.advance_combat_phase(state)
            allies, hostiles = combat_phase.partition_packets(resolving, advance.packets)
            state.ally_continuation = combat_fate.begin_ally_pass(resolving, allies, hostiles, {})
        await db_mutations.save_combat_state(state.combat_id, state.to_dict(), conn=world.pool)
        before = await snapshot(world)
        destination = DESTINATION if geometry == "spatial" else None
        with pytest.raises(ToolError, match=reason):
            await call("activate", id=VEILSTEP, destination=destination)
        assert await snapshot(world) == before
        if flag == "favor":
            await configure(world, "syrath", "seeker")
        elif flag == "ally_continuation":
            state.ally_continuation = None
        else:
            setattr(actor, flag, False)
        assert ("position" in await step(world, call, destination=destination)) == (geometry == "spatial")


@pytest.mark.parametrize("geometry", ["legacy", "none"])
async def test_veilstep_without_placement(world: SimpleNamespace, geometry: str) -> None:
    async with veilstep_scene(world, geometry=geometry) as call:
        before = await checkpoint(world)
        assert "position" not in await step(world, call)
        state = world.ctx.userdata.combat_state
        assert await checkpoint(world) == before == (state.to_dict() if state else None)


SCENARIOS = {
    VEILSTEP: ("patron_combat_edges:veilstep", veilstep_full_move, [()]),
    "syrath_silent_casting": (
        "cast_modifiers:apply_patron_generation",
        hidden_casting_composes_and_persists,
        [("mage", True, 0), ("seeker", True, 0), ("bard", True, 1), ("mage", False, 3)],
    ),
}
