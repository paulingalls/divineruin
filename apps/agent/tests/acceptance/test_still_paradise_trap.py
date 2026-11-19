import json
from unittest.mock import patch
from uuid import uuid4

import pytest
from acceptance.mawling_harness import MawlingHarness
from acceptance.seeds import seed_known_spells
from acceptance.test_still_anchors import declare, destroy, enter, search_round, spell, strike
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from livekit.agents import Agent, AgentSession
from sample_fixtures import published_payloads

import db_activity_queries
import db_mutations
import db_queries
import event_types as E
from caster_state import ConcentrationState, ResonanceTrack
from check_resolution import D20Roll
from fate_tool_boundary import wrap_tool
from mode_tools import enter_mode
from movement_tools import move_player
from party_state import PartyMember
from query_tools import query_info
from session_data import SessionData
from travel_tools import travel


@pytest.fixture
async def paradise(reset_db_pool):
    walk = MawlingHarness()
    origin, zone = (f"still_test_{uuid4().hex}" for _ in range(2))
    try:
        await walk.prepare((18, 18), companion=None, location=origin)
        for location, other, tags, navigation in (
            (origin, zone, [], "known_trail"),
            (zone, origin, ["still"], "established_road"),
        ):
            data = dict(
                id=location,
                name=location,
                tags=tags,
                terrain="grassland",
                region="ashmark",
                region_type="wilderness",
                navigation=navigation,
                exits={"east": {"destination": other}},
            )
            await walk.pool.execute(
                "INSERT INTO locations (id, data) VALUES ($1, $2::jsonb)", location, json.dumps(data)
            )
        for index, pid in enumerate(walk.players):
            row = await player_row(pid)
            row.update(name=("Rowan", "Iona")[index], location_id=origin, saving_throw_proficiencies=[])
            row["attributes"]["wisdom"] = (12, 10)[index]
            await walk.pool.execute("UPDATE players SET data=$2::jsonb WHERE player_id=$1", pid, json.dumps(row))
        await exploration(walk)
        yield walk, origin, zone
    finally:
        await walk.close()


async def exploration(walk):
    await walk.session.aclose()
    rows = [await player_row(pid) for pid in walk.players]
    walk.sd = SessionData(player_id=walk.players[0], location_id=rows[0]["location_id"], room=walk.sd.room)
    for pid in walk.players[1:]:
        walk.sd.party.members.append(PartyMember(pid, ResonanceTrack(), ConcentrationState()))
    walk.session = AgentSession(llm=walk.model, max_tool_steps=5, userdata=walk.sd)
    await walk.session.start(
        Agent(
            instructions="Execute the command.",
            tools=[wrap_tool(tool) for tool in (enter_mode, query_info, move_player, travel)],
        )
    )


async def command(walk, verb, destination, *, actor=None):
    args = {"destination_id": destination}
    if verb == "travel":
        args.update(mode="compressed", hours=1)
    walk.model.commands.append((verb, args))
    with walk.sd._bind_authenticated_actor(actor or walk.players[0], 1, lambda *_: None):
        await walk.session.run(user_input="Execute the next command.")
    result = list(walk.model.receipts.values())[-1]
    assert result.name == verb
    return result.output if result.is_error else json.loads(result.output)


async def player_row(player_id) -> dict:
    player = await db_queries.get_player(player_id)
    assert player is not None
    return player


async def row_snapshot(walk):
    return [(await player_row(pid), await db_activity_queries.get_player_map_progress(pid)) for pid in walk.players]


async def arrive(walk, verb, zone, *, held=False):
    with patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(17 if self.dc == 18 else 20)):
        result = await command(walk, verb, zone)
        assert ("fate_offer" in result) is held
        if held:
            kept = await walk.command("query_info", {"kind": "inventory"})
            return kept["settled_fate"]
        return result


@pytest.mark.parametrize(
    "verb, navigation",
    [
        ("move_player", "established_road"),
        ("travel", "established_road"),
        ("travel", "known_trail"),
    ],
)
async def test_arrival_saves_and_party_departure(paradise, verb, navigation):
    walk, origin, zone = paradise
    if navigation != "established_road":
        await walk.pool.execute(
            "UPDATE locations SET data=jsonb_set(data,'{navigation}',$2::jsonb) WHERE id=$1",
            zone,
            json.dumps(navigation),
        )
        await walk.pool.execute(
            "UPDATE players SET data=jsonb_set(data,'{divine_favor}',$2::jsonb) WHERE player_id=$1",
            walk.players[0],
            json.dumps({"patron": "zhael", "level": 0, "max": 100, "last_whisper_level": 0}),
        )
    result = await arrive(walk, verb, zone, held=navigation == "known_trail")
    host, guest = [row for row, _ in await row_snapshot(walk)]
    assert host["location_id"] == guest["location_id"] == zone
    key = f"still_charm:{zone}"
    assert key not in host.get("flags", {})
    assert json.loads(guest.get("flags", {}).get(key, "null")) == dict(
        location_id=zone, kind="paradise_trap", remaining_zone_hours=None
    )
    assert "Iona does not want to leave" in json.dumps(result["still"])
    assert "Rowan" not in json.dumps(result["still"])

    before, events = await row_snapshot(walk), published_payloads(walk.sd.room)
    for speaker in walk.players:
        with patch(
            "travel_tools.check_resolution.resolve_skill_check_dc", side_effect=AssertionError("rolled navigation")
        ):
            refusal = await command(walk, verb, origin, actor=speaker)
        assert "Iona does not want to leave" in refusal
        assert await row_snapshot(walk) == before
        assert published_payloads(walk.sd.room) == events
        assert walk.sd.location_id == zone

    import still_charm

    await db_mutations.set_player_flag(
        walk.players[1],
        f"still_charm:{origin}",
        json.dumps(dict(location_id=origin, kind="final_stillness", remaining_zone_hours=None)),
    )
    async with walk.pool.acquire() as conn, conn.transaction():
        await still_charm.clear([walk.players[1]], zone, conn=conn)
    await exploration(walk)
    result = await arrive(walk, verb, origin, held=navigation == "known_trail")
    assert isinstance(result, dict) and result.get("moved", result.get("arrived"))
    assert all(row["location_id"] == origin for row, _ in await row_snapshot(walk))


async def test_combat_projects_the_stored_charm(paradise):
    walk, origin, zone = paradise
    await arrive(walk, "move_player", zone)
    await exploration(walk)
    await seed_known_spells(walk.pool, walk.players[1], ("arcane_bolt",))
    response, state = await enter(walk)
    owner = state.still_encounter["owner_id"]
    host, guest = walk.players
    assert not any(c["type"] == "charmed" for c in state.get_participant(host).conditions)
    assert any(c["type"] == "charmed" and c["source"] == owner for c in state.get_participant(guest).conditions)
    assert response["still"]["charmed_player_ids"] == [guest]
    hud = [p for p in published_payloads(walk.sd.room) if p["type"] == E.COMBAT_UI_UPDATE][-1]
    hud_guest = next(p for p in hud["combatants"] if p["id"] == guest)
    assert {"type": "charmed", "source": owner, "stacks": 1} in hud_guest["conditions"]

    search = response["still"]["search_actions"][0]
    await search_round(walk, search)
    revealed = await walk.reload()
    (anchor,) = revealed.still_encounter["revealed_ids"]
    for action in (strike(anchor), spell("arcane_bolt", anchor)):
        assert "Charmed" in await declare(walk, actor_id=guest, error=True, **action)
    assert (await walk.reload()).to_dict() == revealed.to_dict()

    await destroy(walk, anchor)
    for other in revealed.still_encounter["anchor_ids"][1:]:
        await search_round(walk, search)
        await destroy(walk, other)
    assert walk.last_result["still"]["charmed_player_ids"] == []
    guest_row = await player_row(guest)
    assert f"still_charm:{zone}" not in guest_row["flags"]
    await exploration(walk)
    assert (await command(walk, "move_player", origin))["moved"]
    with patch.object(D20Roll, "roll", side_effect=AssertionError("Rolled against a destroyed Still")):
        assert (await command(walk, "move_player", zone))["still"] is None
