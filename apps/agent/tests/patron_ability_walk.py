"""Registered patron commands against a durable, isolated follower."""

import json
import uuid
from contextlib import AsyncExitStack
from unittest.mock import AsyncMock, patch

from acceptance.seeds import seed_player_with_pools
from acceptance.voice_condition_harness import ScenarioModel
from livekit.agents import Agent, AgentSession
from sample_fixtures import make_mock_room

import db_queries
from activate_tools import activate
from query_tools import query_info
from rest_tools import rest
from session_data import SessionData


class AbilityWalk:
    def __init__(self, pool):
        self.pool = pool
        self.player = "patron_" + uuid.uuid4().hex
        self.stack = AsyncExitStack()
        self.validator = lambda *_: None

    async def __aenter__(self):
        await self.stack.__aenter__()
        await seed_player_with_pools(self.pool, player_id=self.player)
        self.stack.push_async_callback(self.pool.execute, "DELETE FROM players WHERE player_id=$1", self.player)
        await self.patch(
            location_id="millhaven_inn",
            divine_favor={"patron": "veythar", "level": 40, "max": 100, "last_whisper_level": 0},
            patron_gifts={"other": {"x": 1}},
            keepsake="unchanged",
        )
        for seam in ("rest_tools.publish_game_event", "rest_tools.publish_resonance_changed"):
            self.stack.enter_context(patch(seam, new_callable=AsyncMock))
        await self.connect()
        return self

    async def __aexit__(self, *args):
        return await self.stack.__aexit__(*args)

    async def connect(self, sd=None):
        self.sd = sd or SessionData(player_id=self.player, location_id="millhaven_inn", room=make_mock_room())
        self.model = ScenarioModel([])
        self.session = AgentSession(llm=self.model, userdata=self.sd)
        await self.session.start(Agent(instructions="Execute the command.", tools=[activate, query_info, rest]))
        self.stack.push_async_callback(self.session.aclose)

    async def patch(self, **data):
        await self.pool.execute(
            "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1", self.player, json.dumps(data)
        )

    async def row(self):
        row = await db_queries.get_player(self.player)
        assert row is not None
        return row

    async def revision(self) -> int:
        return (await db_queries.get_player_at_patron_revision(self.player))[1]

    async def state(self):
        row = await self.row()
        return {key: row.get(key) for key in ("patron_gifts", "divine_favor", "keepsake")}

    async def command(self, name, args, *, error: bool | None = False, actor=None):
        self.model.commands.append((name, args))
        with self.sd._bind_authenticated_actor(actor or self.player, 1, self.validator):
            await self.session.run(user_input="Execute the command.")
        receipt = list(self.model.receipts.values())[-1]
        assert receipt.name == name, receipt.output
        if error is not None:
            assert receipt.is_error == error, receipt.output
        return receipt.output if receipt.is_error else json.loads(receipt.output)

    async def use(self, ability, *, error: bool | None = False, actor=None):
        return await self.command("activate", {"id": ability}, error=error, actor=actor)

    async def abilities(self):
        return (await self.command("query_info", {"kind": "patron"}))["abilities"]
