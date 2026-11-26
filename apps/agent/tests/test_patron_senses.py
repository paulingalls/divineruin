from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import game_tools
from acceptance._capstone_helpers import _d20
from acceptance.seeds import seed_player_with_pools
from livekit.agents.llm import ToolError

import db_activity_queries
from _gods_content import load_gods
from combat_participant import CombatParticipant
from combat_state import CombatState
from movement_tools import move_player
from query_tools import query_info
from rest_tools import rest
from session_data import SessionData
from travel_tools import travel

ROAD = "greyvale_south_road"
TOWN = "millhaven"
INN = "millhaven_inn"
WILDS = "greyvale_wilderness_north"
HOURS = "hours_traveled_since_long_rest"


async def _set_progress(w, *locations):
    await w.pool.executemany(
        "INSERT INTO player_map_progress (player_id, location_id, data) VALUES ($1,$2,'{}') ON CONFLICT DO NOTHING",
        [(w.ids[0], location) for location in locations],
    )


def _graph(**edges):
    return {
        name: {"name": name, "exits": {target: {"destination": target} for target in destinations}}
        for name, destinations in edges.items()
    }


async def deaths_awareness_reads_combat(world):
    w = world
    session = w.ctx.userdata
    await configure(w, "mortaen", "mage", divine_favor={"patron": "mortaen", "level": 0, "max": 100})
    await configure(w, "none", "mage", index=1, hp={"current": 5, "max": 30}, location_id=session.location_id)
    participants = [
        CombatParticipant(pid, name, kind, 10, hp, 20, 14, is_dead=dead, is_fallen=fallen)
        for pid, name, kind, hp, dead, fallen in [
            ("hound", "Hound", "enemy", 4, False, False),
            (w.ids[1], "Ally", "player", 15, False, False),
            ("edge", "At the threshold", "enemy", 5, False, False),
            ("above", "Above the threshold", "enemy", 6, False, False),
            ("corpse", "Corpse", "enemy", 0, True, False),
            (w.ids[0], "Fallen follower", "player", 0, False, True),
        ]
    ]
    session.combat_state = CombatState(
        "wounded", participants, [p.id for p in participants], location_id=session.location_id
    )
    packet = await game_tools(session, query_info)("query_info", kind="patron")
    assert packet["deaths_awareness"]["creatures"] == [
        {"id": "hound", "name": "Hound"},
        {"id": "edge", "name": "At the threshold"},
        {"id": w.ids[0], "name": "Fallen follower"},
    ]
    assert packet["deaths_awareness"]["narration_cue"]
    assert "horizon_sense" not in packet


async def test_deaths_awareness_reads_colocated_party_and_current_patron(world):
    w = world
    session = w.ctx.userdata
    location = session.location_id
    await configure(w, "mortaen", "mage", name="Follower", hp={"current": 15, "max": 20}, location_id=location)
    await configure(w, "none", "mage", index=1, name="Guest", hp={"current": 5, "max": 30}, location_id=location)
    call = game_tools(session, query_info)
    assert (await call("query_info", kind="patron"))["deaths_awareness"]["creatures"] == [
        {"id": w.ids[1], "name": "Guest"}
    ]
    await configure(w, "none", "mage", index=1, location_id=TOWN)
    assert (await call("query_info", kind="patron"))["deaths_awareness"]["creatures"] == []
    await configure(w, "none", "mage", index=1, location_id=location, hp={"current": 7, "max": 30}, maxhp_override=-4)
    assert (await call("query_info", kind="patron"))["deaths_awareness"]["creatures"] == []
    await configure(w, "kaelen", "mage", index=1)
    assert (await call("query_info", kind="patron"))["deaths_awareness"]["creatures"] == [
        {"id": w.ids[1], "name": "Guest"}
    ]
    await configure(w, "none", "mage", index=1)
    with session._bind_authenticated_actor(w.ids[1], 1, lambda *_: None):
        packet = await call("query_info", kind="patron")
        assert packet["synergy"] is None
        assert {"deaths_awareness", "horizon_sense"}.isdisjoint(packet)
    for patron in load_gods():
        pid = patron["god_id"]
        if pid in {"mortaen", "nythera"}:
            continue
        await configure(w, pid, "mage")
        session.party.primary.patron_id = "mortaen"
        packet = await call("query_info", kind="patron")
        assert packet["patron_id"] == pid and packet["synergy"] is not None
        assert {"deaths_awareness", "horizon_sense"}.isdisjoint(packet)


async def horizon_sense_counts_travel_and_uses_map_progress(world):
    w = world
    session = w.ctx.userdata
    session.location_id = ROAD
    for pid in w.ids:
        await seed_player_with_pools(w.pool, player_id=pid)
    await configure(
        w, "nythera", "skirmisher", location_id=ROAD, divine_favor={"patron": "nythera", "level": 0, "max": 100}
    )
    await configure(w, "none", "skirmisher", index=1, location_id=ROAD)
    await _set_progress(w, "a_old_crossroads", "a_old_fork")
    call = game_tools(session, query_info, travel, move_player, rest)
    assert (await call("travel", destination_id=TOWN, mode="compressed", hours=4))["arrived"]
    assert (await call("travel", destination_id=ROAD, mode="scenic", hours=3))["arrived"]
    assert (await row(w))["travel_hours_since_rest"] == 7

    graph = _graph(
        greyvale_south_road=[TOWN, "a_old_crossroads", ROAD],
        millhaven=[ROAD, "new_ruin"],
        a_old_crossroads=["a_old_fork"],
        a_old_fork=["far_marsh"],
        new_ruin=[],
        far_marsh=[],
        unreachable=[],
    )
    fresh = SessionData(player_id=w.ids[0], location_id=ROAD, room=session.room)
    with patch("db_content_queries.get_all_locations", new=AsyncMock(return_value=graph)):
        packet = await game_tools(fresh, query_info)("query_info", kind="patron")
        sense = packet["horizon_sense"]
        assert sense[HOURS] == 7
        assert sense["nearest_unexplored"] == {"name": "new_ruin", "legs": 2}
        assert "deaths_awareness" not in packet
        await _set_progress(w, "new_ruin", "far_marsh")
        sense = (await call("query_info", kind="patron"))["horizon_sense"]
        assert sense[HOURS] == 7
        assert sense["nearest_unexplored"] is None
        assert "nothing unexplored within reach" in sense["narration_cue"].lower()

    assert (await call("move_player", destination_id=TOWN))["moved"]
    assert (await call("move_player", destination_id=INN))["moved"]
    visited = {entry["location_id"] for entry in await db_activity_queries.get_player_map_progress(w.ids[0])}
    assert INN in visited
    assert (await call("query_info", kind="patron"))["horizon_sense"][HOURS] == 7

    remote = w.ids[0] + "_remote"
    await seed_player_with_pools(w.pool, player_id=remote)
    w.ids.append(remote)
    session.party.members.append(SessionData(player_id=remote, location_id=TOWN).party.primary)
    await configure(w, "none", "skirmisher", index=2, location_id=TOWN, travel_hours_since_rest=12)
    session.multiplayer_owner = SimpleNamespace(lifecycle=SimpleNamespace(is_live=lambda _: True))
    with session._bind_authenticated_actor(w.ids[1], 1, lambda *_: None):
        await call("rest", rest_type="short", use_song_of_rest=False)
        assert (await row(w))["travel_hours_since_rest"] == 7
        receipt = await call("rest", rest_type="long", use_song_of_rest=False)
    assert set(receipt["players"]) == set(w.ids[:2])
    assert (await row(w))["travel_hours_since_rest"] == 0
    assert (await row(w, 2))["travel_hours_since_rest"] == 12
    assert (await call("query_info", kind="patron"))["horizon_sense"][HOURS] == 0
    assert {entry["location_id"] for entry in await db_activity_queries.get_player_map_progress(w.ids[0])} == visited


async def test_lost_travel_counts_and_refused_travel_preserves_facts(world):
    w = world
    session = w.ctx.userdata
    session.location_id = TOWN
    await seed_player_with_pools(w.pool, player_id=w.ids[0])
    await configure(w, "nythera", "skirmisher", location_id=TOWN)
    call = game_tools(session, query_info, travel)
    before = (await call("query_info", kind="patron"))["horizon_sense"]
    assert before[HOURS] == 0 and before["nearest_unexplored"]["legs"] == 1
    with patch("check_resolution.dice_roll", return_value=_d20(1)):
        lost = await call("travel", destination_id=WILDS, mode="dangerous", hours=3)
    assert lost["wrong_area"] and not lost["arrived"]
    assert session.location_id == TOWN
    assert {entry["location_id"] for entry in await db_activity_queries.get_player_map_progress(w.ids[0])} == set()
    sense = (await call("query_info", kind="patron"))["horizon_sense"]
    assert sense == {**before, HOURS: 3}

    for destination, mode, hours in [
        (ROAD, "scenic", 0),
        (ROAD, "scenic", -1),
        (ROAD, "invalid", 1),
        ("unknown", "scenic", 1),
    ]:
        with pytest.raises(ToolError):
            await call("travel", destination_id=destination, mode=mode, hours=hours)
    assert (await call("query_info", kind="patron"))["horizon_sense"] == sense
    assert session.location_id == TOWN
    await configure(w, "nythera", "skirmisher", travel_hours_since_rest=None)
    with pytest.raises(ValueError, match="nonnegative integer travel hours"):
        await call("query_info", kind="patron")


SCENARIOS = {
    "mortaen_deaths_awareness": ("patron_senses:deaths_awareness", deaths_awareness_reads_combat, [()]),
    "nythera_horizon_sense": ("patron_senses:horizon_sense", horizon_sense_counts_travel_and_uses_map_progress, [()]),
}
