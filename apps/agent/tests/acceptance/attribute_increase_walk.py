"""Owned command model driving registered progression choices against PostgreSQL."""

import json
from datetime import UTC, datetime

from acceptance.greyvale_arc_walk_harness import ArcWalk
from acceptance.voice_condition_harness import ScenarioModel
from livekit.agents import Agent, AgentSession

import db_queries
import event_types as E
from choice_tools import select
from creation_rules import build_character_data
from hp_scaling import calculate_max_hp
from query_tools import query_info
from quest_tools import update_quest
from rest_tools import rest
from rules_engine import XP_FOR_LEVEL
from session_data import SessionData


class IncreaseWalk(ArcWalk):
    async def setup(self, harness):
        await self.start(
            harness,
            "update_quest",
            stage=7,
            agent=Agent(instructions="Execute the spoken command.", tools=[update_quest, select, query_info, rest]),
        )
        await self.seed(3)
        return self

    async def seed(self, level, archetype="warrior", attributes=None):
        row = build_character_data(
            "Increase", "human", archetype, None, "", created_at=datetime(2026, 11, 18, tzinfo=UTC)
        )
        if attributes:
            row["attributes"].update(attributes)
        row.update(level=level, xp=550 if level == 3 else XP_FOR_LEVEL[level], location_id="millhaven_inn")
        hp = calculate_max_hp(archetype, level, (row["attributes"]["constitution"] - 10) // 2)
        row["hp"] = {"current": 5, "max": hp}
        await self.pool.execute("UPDATE players SET data=$2::jsonb WHERE player_id=$1", self.player, json.dumps(row))
        self.sd.location_id = "millhaven_inn"
        return await self.row()

    async def row(self):
        row = await db_queries.get_player(self.player)
        assert row is not None
        return row

    async def command(self, name, args, speech="Execute the command."):
        self.model.commands.append((name, args))
        with self.sd._bind_authenticated_actor(self.player, 1, lambda *_: None):
            await self.session.run(user_input=speech)
        receipt = list(self.model.receipts.values())[-1]
        assert receipt.name == name
        return receipt

    async def publish(self, raw, **kwargs):
        event = json.loads(raw)
        if event["type"] == E.SESSION_INIT:
            pid = event["character"]["player_id"]
            assert kwargs["destination_identities"] == [pid]
            row = await db_queries.get_player(pid)
            assert row is not None
            for key in ("attributes", "hp", "ac", "stamina", "focus"):
                if key in row:
                    assert event["character"][key] == row[key]
        self.events.append(event)

    async def reload(self, harness):
        await self.session.aclose()
        self.sd = SessionData(player_id=self.player, location_id="millhaven_inn", room=self.sd.room)
        self.model = ScenarioModel([])
        self.session = AgentSession(llm=self.model, userdata=self.sd)
        await self.session.start(
            Agent(instructions="Execute the spoken command.", tools=[update_quest, select, query_info, rest])
        )
        harness.stack.callback(lambda: harness.run_sync(self.session.aclose()))
