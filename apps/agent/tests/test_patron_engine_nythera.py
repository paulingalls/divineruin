import asyncio
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from _patron_engine_fixtures import configure
from _patron_gateway_fixtures import (
    GIFT,
    HALL,
    MARKET,
    MILL,
    WILDERNESS,
    call,
    charm,
    cross,
    offer,
    party_rows,
    prepare,
    snapshot,
    visit,
)
from _unbound_path_fixtures import encounter
from _unbound_path_fixtures import world as world
from acceptance._capstone_helpers import _d20
from livekit.agents.llm import ToolError
from sample_fixtures import published_payloads
from test_unbound_alone_bonus import check

import db
import db_content_queries
import db_queries
import event_types as E
from combat_agent import CombatAgent
from dispatch_agent import DispatchAgent


async def uncharted_senses_uses_map_history(world, archetype, skill, bonus):
    w = world
    await configure(w, "nythera", archetype)
    await w.pool.execute(
        "INSERT INTO player_map_progress (player_id, location_id, data) VALUES ($1,$2,$3::jsonb)",
        w.ids[0],
        w.ctx.userdata.location_id,
        json.dumps({"revisited": False}),
    )
    assert (await check(w, skill))["total"] == 11 + bonus
    await w.pool.execute(
        "UPDATE player_map_progress SET data='{" + '"revisited":true' + "}' WHERE player_id=$1",
        w.ids[0],
    )
    assert (await check(w, skill))["total"] == 11


async def uncharted_handling_adds_minor_bonus(world, archetype, bonus):
    from check_tools import _check_impl

    w = world
    await configure(w, "nythera", archetype)
    await w.pool.execute(
        "INSERT INTO player_map_progress (player_id, location_id, data) VALUES ($1,$2,'{}')",
        w.ids[0],
        w.ctx.userdata.location_id,
    )
    with patch("check_resolution.dice_roll", side_effect=[_d20(4), _d20(17)]) as dice:
        packet = json.loads(await _check_impl(w.ctx, "skill", skill="animal_handling", difficulty="moderate"))
    assert packet["roll"] == 4 and dice.call_count == 1
    assert packet["total"] == 4 + packet["modifier"]
    assert packet["modifier"] == bonus
    await w.pool.execute(
        "UPDATE player_map_progress SET data=$2::jsonb WHERE player_id=$1",
        w.ids[0],
        json.dumps({"revisited": True}),
    )
    with patch("check_resolution.dice_roll", return_value=_d20(4)):
        revisited = json.loads(await _check_impl(w.ctx, "skill", skill="animal_handling", difficulty="moderate"))
    assert revisited["roll"] == 4
    assert revisited["modifier"] == 0
    assert revisited["total"] == 4


async def test_guest_discovery_and_reroll_use_first_stay(world):
    from unittest.mock import AsyncMock

    import db_mutations_conditions
    import db_mutations_skill_advancement
    import db_queries
    from check_skill import _check_skill_run
    from check_tools import _check_impl
    from skill_check_effects import SkillCheckEffects

    w = world
    await configure(w, "nythera", "spy", index=1)
    await w.pool.execute(
        "INSERT INTO player_map_progress (player_id, location_id, data) VALUES ($1,$2,'{}')",
        w.ids[1],
        w.ctx.userdata.location_id,
    )
    with (
        w.ctx.userdata._bind_authenticated_actor(w.ids[1], 4, lambda *_: None),
        patch("check_resolution.dice_roll", return_value=_d20(11)),
    ):
        packet = json.loads(
            await _check_impl(
                w.ctx,
                "discover",
                skill="perception",
                content=MagicMock(
                    get_item=AsyncMock(return_value=None),
                    get_location=AsyncMock(return_value={"hidden_elements": []}),
                ),
            )
        )
        assert packet["total"] == 14
        async with w.db.transaction() as conn:
            player = await db_queries.get_player(w.ids[1], conn=conn, for_update=True)
            effects = SkillCheckEffects()
            packet = json.loads(
                await _check_skill_run(
                    w.ctx,
                    "investigation",
                    "moderate",
                    "reroll",
                    hearing_only=False,
                    queries=db_queries,
                    mutations=db_mutations_skill_advancement,
                    db_mod=w.db,
                    conditions_mutations=db_mutations_conditions,
                    effects=effects,
                    conn=conn,
                    locked_player=player,
                    reroll_dc=12,
                )
            )
        assert packet["total"] == 14 and effects.events[0][1]["total"] == 14


@pytest.mark.parametrize("first_stay,bonus", [(True, 3), (False, 0)])
async def test_choir_search_carries_uncharted_senses(first_stay, bonus, mock_combat_agent_factory):
    import combat_packet
    from combat_phase import ResolutionPacket
    from declarations import resolve_declaration
    from tests.combat.test_choir_encounter import start_choir

    ctx, _, mutations, queries = await start_choir()
    state = ctx.userdata.combat_state
    actor = state.get_participant("player_1")
    queries.get_player.return_value = {
        **queries.get_player.return_value,
        "class": "seeker",
        "divine_favor": {"patron": "nythera", "level": 40, "max": 100},
    }
    decl = resolve_declaration({"type": "interact", "action": "choir_search_perception", "target_id": "choir_sound"})
    with (
        patch("check_resolution.dice_roll", return_value=_d20(10)),
        patch("choir_encounter.check_first_stay", return_value=first_stay),
    ):
        packet = await combat_packet._resolve_one_packet(
            ctx.userdata,
            state,
            ResolutionPacket(actor_id=actor.id, declaration=decl, initiative=actor.initiative),
            mutations=mutations,
            queries=queries,
            resolver=None,
            concentration_break_mod=None,
        )
    assert packet["total"] == 13 + bonus
    assert (packet.get("gift_name") == "Uncharted Senses") is first_stay


async def gateway_scenario(world):
    agent = await prepare(world)
    session = world.ctx.userdata
    host, follower = world.ids
    await world.pool.execute(
        "INSERT INTO player_quests (player_id, quest_id, data) VALUES ($1, 'greyvale_anomaly', jsonb_build_object('current_stage', 0))",
        host,
    )
    gift = await offer(world, agent)
    assert gift["available"] and gift["recharge"] == "per_session"
    assert "target_id" in gift["activation_hint"]
    assert gift["destinations"] == [{"id": MILL, "name": "Millhaven"}]
    destination = gift["destinations"][0]["id"]
    result = await call(world, agent, id=gift["id"], target_id=destination)
    location = await db_content_queries.get_location(MILL)
    assert location is not None
    assert result["location"]["id"] == MILL
    assert result["location"]["name"] == location["name"]
    assert result["location"]["description"] == location["description"]
    assert result["player"]["name"] == "Follower"
    assert [npc["id"] for npc in result["npcs"]] == [npc["id"] for npc in await db_queries.get_npcs_at_location(MILL)]
    assert [target["id"] for target in result["targets"]] == [
        target["npc_id"] for target in await db_queries.get_targets_at_location(MILL)
    ]
    quest = await db_queries.get_player_quest(host, "greyvale_anomaly")
    assert quest is not None and quest["current_stage"] == 1
    assert len(result["quest_updates"]) == 1
    assert session.recent_events[-1] == f"Opened Beyond the Horizon to {MILL}"
    assert "quieter" in result["quest_updates"][0]["narrative_beat"]
    rows = await party_rows(world)
    for pid in world.ids:
        assert rows[pid]["location_id"] == MILL and rows[pid]["travel_state"] is None
        assert await world.pool.fetchval(
            "SELECT 1 FROM player_map_progress WHERE player_id = $1 AND location_id = $2", pid, MILL
        )
        assert MILL in session.player_summary_metrics[pid]["locations_visited"]
    assert rows[host]["patron_gifts"] == {"unrelated": {"spent": True}}
    assert rows[follower]["patron_gifts"] == {"unrelated": {"spent": True}, GIFT: {"spent": True}}
    assert rows[follower]["resonance"] == {"current": 14, "flickering_bonus": 2}
    assert rows[host]["resonance"]["current"] == session.member_state(host).resonance.current == 3
    track = session.member_state(follower).resonance
    assert (track.current, track.flickering_bonus) == (14, 2)
    assert session.location_id == MILL and MILL in session.session_locations_visited
    events = published_payloads(session.room)
    (arrival,) = [event for event in events if event["type"] == E.LOCATION_CHANGED]
    assert arrival["previous_location"] == MARKET and arrival["new_location"] == MILL
    assert arrival["location_name"] == location["name"]
    assert arrival["region"] == location["region"] and arrival["tags"] == location["tags"]
    assert arrival["atmosphere"] == location["atmosphere"]
    assert arrival["connections"] == db.extract_exit_connections(location["exits"])
    assert "ambient_sounds" in arrival and arrival["time_of_day"] == session.world_time
    assert [event["caster_id"] for event in events if event["type"] == E.RESONANCE_CHANGED] == [follower]
    (patron,) = [event for event in events if event["type"] == E.PATRON_ABILITIES_UPDATED]
    assert patron["player_id"] == follower
    assert next(row for row in patron["abilities"] if row["id"] == GIFT)["spent"]
    await check_mobile_arrival(arrival)


async def check_mobile_arrival(arrival):
    bridge = await asyncio.create_subprocess_exec(
        "bun",
        "test",
        "src/__tests__/use-game-events.character.test.ts",
        "-t",
        "location_changed updates session and character stores",
        cwd=Path(__file__).resolve().parents[2] / "mobile",
        env={**os.environ, "NYTHERA_GATEWAY_EVENT": json.dumps(arrival)},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        output, _ = await asyncio.wait_for(bridge.communicate(), 15)
    except TimeoutError:
        bridge.kill()
        await bridge.communicate()
        raise
    assert bridge.returncode == 0 and "1 pass" in output.decode(), output.decode()


@pytest.mark.parametrize(
    ("destination", "message"),
    [
        (HALL, "visited"),
        (MARKET, "current location"),
        ("unknown_gateway_location", "Unknown"),
        (None, "target_id"),
    ],
)
async def test_gateway_refuses_invalid_destinations(world, destination, message):
    agent = await prepare(world)
    if destination == "unknown_gateway_location":
        await visit(world, world.ids[1], destination)
    before = await snapshot(world, agent)
    with pytest.raises(ToolError, match=message):
        await cross(world, agent, destination)
    assert await snapshot(world, agent) == before
    assert (await cross(world, agent))["location"]["id"] == MILL


async def test_gateway_refuses_registered_combat_tool(world):
    exploration = await prepare(world)
    encounter(world)
    combat = CombatAgent()
    before = await snapshot(world, combat)
    with pytest.raises(ToolError, match="during combat"):
        await cross(world, combat)
    assert await snapshot(world, combat) == before
    world.ctx.userdata.combat_state = None
    assert (await cross(world, exploration))["location"]["id"] == MILL


async def test_gateway_respects_still_charm_on_other_member(world):
    agent = await prepare(world)
    await charm(world, world.ids[0])
    before = await snapshot(world, agent)
    with pytest.raises(ToolError, match="Host does not want to leave the Still"):
        await cross(world, agent)
    assert await snapshot(world, agent) == before
    await world.pool.execute("UPDATE players SET data = data - 'flags' WHERE player_id = $1", world.ids[0])
    assert (await cross(world, agent))["location"]["id"] == MILL


async def test_gateway_requires_exalted_and_recharges_per_session(world):
    agent = await prepare(world, favor=74)
    gift = await offer(world, agent)
    assert not gift["available"] and "destinations" not in gift
    before = await snapshot(world, agent)
    with pytest.raises(ToolError, match="Exalted"):
        await cross(world, agent)
    assert await snapshot(world, agent) == before
    await world.pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{divine_favor,level}', '75') WHERE player_id = $1", world.ids[1]
    )
    assert (await offer(world, agent))["available"]
    assert (await cross(world, agent))["location"]["id"] == MILL
    gift = await offer(world, agent)
    assert gift["spent"] and not gift["available"] and "destinations" not in gift
    before = await snapshot(world, agent)
    with pytest.raises(ToolError, match="new session"):
        await cross(world, agent, MARKET)
    assert await snapshot(world, agent) == before


@pytest.mark.parametrize("destination", [WILDERNESS, HALL])
async def test_gateway_preserves_destination_agent_context(world, destination):
    agent = await prepare(world)
    await visit(world, world.ids[1], destination)
    result = await cross(world, agent, destination)
    if destination == HALL:
        next_agent, result = result
        assert isinstance(next_agent, DispatchAgent)
    else:
        assert agent._agent_type == "wilderness"
    assert result["location"]["id"] == destination
    rows = await party_rows(world)
    assert {row["location_id"] for row in rows.values()} == {destination}
    assert rows[world.ids[1]]["patron_gifts"][GIFT]["spent"]


SCENARIOS = {
    GIFT: ("patron_gateway:activate_locked", gateway_scenario, [()]),
    "nythera_uncharted_senses": (
        "patron_gifts:skill_gift",
        uncharted_senses_uses_map_history,
        [(a, s, 3) for a in ("seeker", "spy") for s in ("investigation", "perception")]
        + [("bard", "investigation", 0), ("seeker", "athletics", 0)],
    ),
    "nythera_uncharted_handling": (
        "patron_gifts:skill_gift",
        uncharted_handling_adds_minor_bonus,
        [("druid", 1), ("beastcaller", 1), ("bard", 0)],
    ),
}
