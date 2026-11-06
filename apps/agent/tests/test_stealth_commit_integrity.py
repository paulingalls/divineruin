"""Stealth adopts conditions and publishes only after its transaction commits."""

import json
from contextlib import asynccontextmanager
from unittest.mock import patch
from uuid import uuid4

import pytest
from combat._helpers import _resolution_state
from sample_fixtures import make_context
from syrath_valdris_fixtures import hide, player_row
from syrath_valdris_fixtures import world as world

import db_mutations


@pytest.mark.parametrize("failure", ["commit", "publish", None])
async def test_stealth_condition_snapshot_follows_commit(world, failure):
    ids, conn, database, _ = world
    ctx = make_context(player_id=ids[0])
    inspired = {"type": "inspired", "duration": 2, "source": "ally"}
    await conn.execute(
        "UPDATE players SET data=jsonb_set(data, '{conditions}', $2::jsonb) WHERE player_id=$1",
        ids[0],
        json.dumps([inspired]),
    )
    state = _resolution_state(player_id=ids[0], combat_id="stealth_" + uuid4().hex, player_conditions=[inspired])
    ctx.userdata.combat_state = state
    await conn.execute(
        "INSERT INTO combat_instances (combat_id, data) VALUES ($1, $2::jsonb)",
        state.combat_id,
        json.dumps(state.to_dict()),
    )
    scope = database.transaction
    committed = False
    events = []

    @asynccontextmanager
    async def transaction():
        nonlocal committed
        async with scope() as tx_conn:
            yield tx_conn
            if failure == "commit":
                raise RuntimeError("commit failed")
        committed = True

    async def publish(*args, **kwargs):
        events.append(args[1])
        if failure == "publish":
            raise RuntimeError("publication failed")
        if failure == "commit":
            return
        assert committed
        assert ctx.userdata.combat_state.get_participant(ids[0]).conditions == []

    database.transaction = transaction
    with patch("check_tools.publish_game_event", publish):
        if failure:
            with pytest.raises(RuntimeError, match="failed"):
                await hide(world, ctx)
        else:
            await hide(world, ctx)
    player = await player_row(conn, ids[0])
    saved = await db_mutations.load_combat_state(state.combat_id, conn=conn)
    assert saved is not None
    expected = [inspired] if failure == "commit" else []
    persisted_actor = saved.get_participant(ids[0])
    memory_actor = ctx.userdata.combat_state.get_participant(ids[0])
    assert persisted_actor is not None and memory_actor is not None
    assert player["conditions"] == persisted_actor.conditions == expected
    assert memory_actor.conditions == expected
    assert player.get("flags", {}).get("concealed") is (None if failure == "commit" else True)
    if failure == "commit":
        assert events == []
