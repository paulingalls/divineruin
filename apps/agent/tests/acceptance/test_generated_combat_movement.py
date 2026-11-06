"""Concurrent movement cannot change a generated fight's environment."""

import asyncio
import json
from random import Random
from typing import cast
from uuid import uuid4

import pytest
from acceptance.loot_harness import LootHarness
from livekit.agents import Agent, AgentSession, llm
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS

import combat_entry
import db_content_queries
import movement_tools
from mode_tools import enter_mode
from movement_tools import move_player


@pytest.fixture
def mock_combat_agent_factory():
    return None


class ParallelStream(llm.LLMStream):
    async def _run(self):
        model = cast(ParallelModel, self._llm)
        for item in self._chat_ctx.items:
            if isinstance(item, llm.FunctionCallOutput):
                model.receipts[item.name] = item
        if model.pending:
            model.pending = False
            calls = [
                ("enter_mode", {"mode": "combat", "difficulty": "standard"}),
                ("move_player", {"destination_id": "accord_market_square"}),
            ]
            delta = llm.ChoiceDelta(
                role="assistant",
                tool_calls=[
                    llm.FunctionToolCall(name=name, arguments=json.dumps(args), call_id=uuid4().hex)
                    for name, args in calls
                ],
            )
        else:
            delta = llm.ChoiceDelta(role="assistant", content="Done.")
        self._event_ch.send_nowait(llm.ChatChunk(id=uuid4().hex, delta=delta))


class ParallelModel(llm.LLM):
    def __init__(self):
        super().__init__()
        self.pending = True
        self.receipts = {}

    def chat(self, *, chat_ctx, tools=None, conn_options=DEFAULT_API_CONNECT_OPTIONS, **kwargs):
        return ParallelStream(self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options)


async def test_generated_entry_serializes_movement(reset_db_pool, monkeypatch):
    h = LootHarness()
    ready, proceed = asyncio.Event(), asyncio.Event()

    class ObservedLock(asyncio.Lock):
        async def acquire(self):
            if self.locked():
                proceed.set()
            return await super().acquire()

    real_catalog = combat_entry.query_creatures_by_region
    real_move = movement_tools._move_player_impl
    real_arrival = movement_tools.apply_arrival

    async def catalog(*args, **kwargs):
        ready.set()
        await asyncio.wait_for(proceed.wait(), 10)
        return await real_catalog(*args, **kwargs)

    async def move(*args, **kwargs):
        await asyncio.wait_for(ready.wait(), 10)
        return await real_move(*args, **kwargs)

    async def arrival(*args, **kwargs):
        result = await real_arrival(*args, **kwargs)
        proceed.set()
        return result

    try:
        await h.prepare(location="greyvale_south_road")
        for pid in h.players:
            await h.pool.execute(
                "UPDATE players SET data=jsonb_set(data, '{location_id}', to_jsonb($2::text)) WHERE player_id=$1",
                pid,
                h.sd.location_id,
            )
        await h.session.aclose()
        h.sd.combat_state_lock = ObservedLock()
        model = ParallelModel()
        h.session = AgentSession(llm=model, userdata=h.sd)
        await h.session.start(Agent(instructions="Execute the commands.", tools=[enter_mode, move_player]))
        monkeypatch.setattr(combat_entry, "query_creatures_by_region", catalog)
        monkeypatch.setattr(combat_entry, "Random", lambda: Random(0))
        monkeypatch.setattr(movement_tools, "_move_player_impl", move)
        monkeypatch.setattr(movement_tools, "apply_arrival", arrival)
        with h.sd._bind_authenticated_actor(h.players[0], 1, lambda *_: None):
            await h.session.run(user_input="Begin the encounter while moving onward.")
        assert set(model.receipts) == {"enter_mode", "move_player"}
        assert not model.receipts["enter_mode"].is_error
        state = await h.reload()
        location = await db_content_queries.get_location(state.location_id)
        assert location is not None
        assert state.location_id == h.sd.location_id == "greyvale_south_road"
        assert state.terrain == location["terrain"] == "farmland"
        for pid in h.players:
            assert (
                await h.pool.fetchval("SELECT data->>'location_id' FROM players WHERE player_id=$1", pid)
                == state.location_id
            )
        for enemy in (p for p in state.participants if p.type == "enemy"):
            row = await h.pool.fetchval("SELECT data FROM creatures WHERE id=$1", enemy.creature_id)
            assert row is not None
            row = json.loads(row)
            assert location["region"] in row["regions"] and state.terrain in row["terrains"]
        assert model.receipts["move_player"].is_error
        assert "combat" in model.receipts["move_player"].output.lower()
    finally:
        await h.close()
