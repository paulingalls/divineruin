"""Deterministic public commands and worker services for purification proofs."""

import asyncio
import json
from contextlib import ExitStack
from typing import Any, cast
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from livekit.agents import Agent, AgentSession, llm
from sample_fixtures import make_mock_room

import async_worker
import db
from activity_templates import build_narration_prompt
from activity_tools import begin_activity
from dialogue_parser import Segment
from session_data import SessionData


class CommandStream(llm.LLMStream):
    async def _run(self):
        model = cast(CommandModel, self._llm)
        for item in self._chat_ctx.items:
            if isinstance(item, llm.FunctionCallOutput):
                model.receipt = item
        if model.pending:
            model.pending = False
            delta = llm.ChoiceDelta(
                role="assistant",
                tool_calls=[
                    llm.FunctionToolCall(
                        name="begin_activity",
                        arguments=json.dumps(model.arguments),
                        call_id=uuid4().hex,
                    )
                ],
            )
        else:
            delta = llm.ChoiceDelta(role="assistant", content="Done.")
        self._event_ch.send_nowait(llm.ChatChunk(id=uuid4().hex, delta=delta))


class CommandModel(llm.LLM):
    pending: bool = False
    arguments: dict
    receipt: llm.FunctionCallOutput

    def chat(self, *, chat_ctx, tools=None, conn_options=None, **kwargs):
        from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS

        return CommandStream(
            self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options or DEFAULT_API_CONNECT_OPTIONS
        )


class PurificationHarness:
    async def start(self, pid=None, class_="artificer", item="rend_shard", held=3, clean=5):
        self.pool = await db.get_pool()
        self.pid = pid or f"purify_{uuid4().hex}"
        self.owns_player = pid is None
        if self.owns_player:
            await self.pool.execute(
                "INSERT INTO players(player_id,data) VALUES($1,$2::jsonb)",
                self.pid,
                json.dumps({"name": "Artificer", "class": class_, "location_id": "accord_guild_hall"}),
            )
        self.item = item
        for tainted, quantity in [(True, held), (False, clean)]:
            if quantity:
                await self.pool.execute(
                    "INSERT INTO player_inventory(player_id,item_id,tainted,data) VALUES($1,$2,$3,$4::jsonb)",
                    self.pid,
                    item,
                    tainted,
                    json.dumps({"quantity": quantity, "source": "fixture"}),
                )
        self.sd = SessionData(player_id=self.pid, location_id="accord_guild_hall", room=make_mock_room())
        self.model = CommandModel()
        self.session = AgentSession(llm=self.model, userdata=self.sd)
        await self.session.start(Agent(instructions="Execute the command.", tools=[begin_activity]))
        return self

    async def begin(self, quantity=2, error=False) -> Any:
        self.model.arguments = {"activity": {"kind": "purification", "item_id": self.item, "quantity": quantity}}
        self.model.pending = True
        with self.sd._bind_authenticated_actor(self.pid, 1, lambda *_: None):
            await self.session.run(user_input="Begin purification.")
        receipt = self.model.receipt
        assert receipt.is_error is error, receipt.output
        return receipt.output if error else json.loads(receipt.output)

    async def rows(self):
        return [
            dict(r)
            for r in await self.pool.fetch(
                "SELECT item_id,tainted,data FROM player_inventory WHERE player_id=$1 ORDER BY item_id,tainted",
                self.pid,
            )
        ]

    async def due(self, activity_id):
        await self.pool.execute(
            "UPDATE async_activities SET data=jsonb_set(data,'{resolve_at}','\"2000-01-01T00:00:00+00:00\"') WHERE id=$1",
            activity_id,
        )

    async def activity(self, activity_id):
        activity = await async_worker.db_activity_queries.get_activity(activity_id)
        if activity is None:
            raise ValueError(f"Missing persisted activity: {activity_id}")
        return activity

    async def close(self):
        await self.session.aclose()
        await self.pool.execute("DELETE FROM async_activities WHERE player_id=$1", self.pid)
        if self.owns_player:
            await self.pool.execute("DELETE FROM players WHERE player_id=$1", self.pid)


def worker_services():
    async def narrate(outcome, player, activity):
        build_narration_prompt(activity["activity_type"], outcome)
        return (
            [Segment(character="DM_NARRATOR", emotion="neutral", text="The taint fades.")],
            "The taint fades.",
            "Purified.",
        )

    stack = ExitStack()
    stack.enter_context(patch.object(async_worker, "generate_activity_narration", narrate))
    for name in ["synthesize_segments", "generate_world_news", "send_push_notification", "generate_notification_hook"]:
        stack.enter_context(patch.object(async_worker, name, AsyncMock(return_value="Purified.")))
    # Exercise real progress prompt construction, replacing only our provider transport.
    from types import SimpleNamespace

    import narration

    response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="The work begins.\nThe taint thins.\nClean material remains.")],
        usage=SimpleNamespace(input_tokens=0, output_tokens=0),
    )

    async def progress(**kwargs):
        assert "purifying" in kwargs["messages"][0]["content"]
        return response

    stack.enter_context(patch.object(narration._client.messages, "create", progress))
    return stack


async def main():
    import sys

    h = await PurificationHarness().start(pid=sys.argv[1])
    try:
        result = await h.begin()
        print(json.dumps(result), flush=True)
        await asyncio.to_thread(input)
        await h.due(result["activity_id"])
        with worker_services():
            await async_worker.resolve_due_activities()
        print(json.dumps(await h.activity(result["activity_id"])), flush=True)
        await asyncio.to_thread(input)
    finally:
        await h.close()
        await db.close_all()
