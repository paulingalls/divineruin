"""Malformed durable patron facts refuse at their production read boundaries."""

import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from combat._helpers import _resolution_state
from livekit.agents.llm import ToolError
from sample_fixtures import make_context
from syrath_valdris_fixtures import cast, player_row
from syrath_valdris_fixtures import world as world

import db_mutations


@pytest.mark.parametrize(
    "patron,key,value,message",
    [
        ("syrath", "concealed", "false", "Malformed stored concealment"),
        ("valdris", "grievance:guildmaster_torin", "bogus", "Malformed stored grievance"),
    ],
)
async def test_corrupt_fact_refuses_cast_before_writes_or_events(world, patron, key, value, message):
    ids, conn, _, _ = world
    await conn.execute(
        "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1",
        ids[0],
        json.dumps({"divine_favor": {"patron": patron}, "flags": {key: value}}),
    )
    before = await player_row(conn, ids[0])
    ctx = make_context(player_id=ids[0])
    with (
        patch("resonance_events.publish_resonance_changed", new_callable=AsyncMock) as resonance,
        patch("hollow_echo_events.publish_hollow_echo", new_callable=AsyncMock) as echo,
    ):
        with pytest.raises(ToolError, match=message):
            await cast(world, ctx, "arcane_haste", target="guildmaster_torin")
        resonance.assert_not_awaited()
        echo.assert_not_awaited()
    assert await player_row(conn, ids[0]) == before
    assert ctx.userdata.resonance.current == 0


async def test_corrupt_hostility_refuses_encounter_load(world):
    ids, conn, _, _ = world
    state = _resolution_state(player_id=ids[0], combat_id="fact_" + uuid4().hex)
    data = state.to_dict()
    data["first_hostility"] = {ids[0]: "hostile"}
    await db_mutations.save_combat_state(state.combat_id, data, conn=conn)
    with pytest.raises(ValueError, match="Malformed first_hostility"):
        await db_mutations.load_combat_state(state.combat_id, conn=conn)
    saved = await conn.fetchval("SELECT data FROM combat_instances WHERE combat_id=$1", state.combat_id)
    assert json.loads(saved) == data
