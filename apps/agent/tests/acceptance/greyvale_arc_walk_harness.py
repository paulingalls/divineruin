"""Real quest rows and registered command receipts for the Greyvale arc."""

import json
from typing import cast
from uuid import uuid4

import asyncpg
from acceptance.seeds import seed_player
from acceptance.voice_condition_harness import ScenarioModel
from livekit.agents import Agent, AgentSession
from sample_fixtures import make_mock_room

import db
import db_content_queries
import db_queries
import event_types as E
from exploration_agent import EXPLORATION_TOOLS
from session_data import SessionData

ROAD = "greyvale_south_road"
TOWN = "millhaven"
QUEST = "greyvale_anomaly"
REWARDS = {E.XP_AWARDED, E.DISPOSITION_CHANGED, E.QUEST_UPDATED}


class ArcWalk:
    async def start(self, harness, tool, stage: int | None = 0, status="active"):
        self.pool = await db.get_pool()
        redis = await db.get_redis()
        await redis.delete("location:millhaven")
        self.player = f"arc_{uuid4().hex}"
        self.events = []
        self.tool = tool
        await seed_player(self.pool, player_id=self.player, class_="warrior", location_id=ROAD)
        await self.pool.execute("UPDATE players SET data=data || '{\"xp\":0}'::jsonb WHERE player_id=$1", self.player)
        if stage is not None:
            await self.quest_row(QUEST, stage, status)
        room = make_mock_room()
        room.local_participant.publish_data.side_effect = self.publish
        self.sd = SessionData(player_id=self.player, location_id=ROAD, room=room)
        self.model = ScenarioModel([])
        tools = [t for t in EXPLORATION_TOOLS if t.__name__ in {"move_player", "travel"}]
        self.session = AgentSession(llm=self.model, userdata=self.sd)
        await self.session.start(Agent(instructions="Execute the command.", tools=tools))
        harness.stack.callback(lambda: harness.run_sync(self.session.aclose()))
        return self

    async def quest_row(self, quest, stage=0, status="active"):
        await self.pool.execute(
            "INSERT INTO player_quests (player_id,quest_id,data) VALUES ($1,$2,$3::jsonb)",
            self.player,
            quest,
            json.dumps({"current_stage": stage, "status": status}),
        )

    async def snapshot(self):
        player = await db_queries.get_player(self.player)
        assert player is not None
        rows = await self.pool.fetch(
            "SELECT quest_id,data FROM player_quests WHERE player_id=$1 ORDER BY quest_id", self.player
        )
        return (
            [dict(row) for row in rows],
            player.get("xp", 0),
            await db_queries.get_npc_disposition("guildmaster_torin", self.player),
        )

    async def publish(self, raw, **kwargs):
        event = json.loads(raw)
        # A separate pool connection observes only committed writes.
        async with self.pool.acquire() as acquired:
            conn = cast(asyncpg.Connection, acquired)
            player = await db_queries.get_player(self.player, conn=conn)
            assert player is not None
            if event["type"] == E.LOCATION_CHANGED:
                assert player["location_id"] == self.sd.location_id
            if event["type"] in REWARDS:
                stage = await conn.fetchval(
                    "SELECT max((data->>'current_stage')::int) FROM player_quests WHERE player_id=$1",
                    self.player,
                )
                assert stage is not None and stage >= 1
                assert player["xp"] >= 50
            if event["type"] == E.XP_AWARDED:
                assert player["xp"] == event["new_xp"]
            if event["type"] == E.DISPOSITION_CHANGED:
                assert await db_queries.get_npc_disposition(event["npc_id"], self.player, conn=conn) == event["new"]
            if event["type"] == E.QUEST_UPDATED:
                persisted = await db_queries.get_player_quest(self.player, event["quest_id"], conn=conn)
                assert persisted is not None
                assert persisted["current_stage"] == event["new_stage"]
        self.events.append(event)

    async def arrive(self, destination=TOWN):
        args = {"destination_id": destination}
        if self.tool == "travel":
            args["mode"] = "compressed"
        self.model.commands.append((self.tool, args))
        with self.sd._bind_authenticated_actor(self.player, 1, lambda *_: None):
            await self.session.run(user_input="Execute the next command.")
        receipt = list(self.model.receipts.values())[-1]
        assert receipt.name == self.tool and not receipt.is_error, receipt.output
        result = json.loads(receipt.output)
        assert result["arrived" if self.tool == "travel" else "moved"]
        return result

    async def rewarded(self, result):
        rows, xp, disposition = await self.snapshot()
        assert json.loads(rows[0]["data"])["current_stage"] == 1
        assert xp == 50 and disposition == "friendly"
        quest = await db_content_queries.get_quest(QUEST)
        assert quest is not None
        (update,) = result["quest_updates"]
        assert update["quest_id"] == QUEST and update["new_stage"] == 1
        assert update["narrative_beat"] == quest["stages"][0]["on_complete"]["narrative_beat"]
        assert update["objective"] == quest["stages"][1]["objective"]
        assert {"type": "xp", "amount": 50, "leveled_up": False} in update["rewards_applied"]
        for kind in REWARDS:
            assert len([e for e in self.events if e["type"] == kind]) == 1
        xp_event = next(e for e in self.events if e["type"] == E.XP_AWARDED)
        assert xp_event["amount"] == xp_event["new_xp"] == 50
        disposition_event = next(e for e in self.events if e["type"] == E.DISPOSITION_CHANGED)
        assert disposition_event["previous"] == "neutral" and disposition_event["new"] == "friendly"
        types = [e["type"] for e in self.events]
        assert types.index(E.LOCATION_CHANGED) < types.index(E.QUEST_UPDATED)
        assert next(e for e in self.events if e["type"] == E.QUEST_UPDATED)["objective"] == update["objective"]

    async def unchanged_arrival(self, destination=TOWN):
        before = await self.snapshot()
        self.events.clear()
        result = await self.arrive(destination)
        assert await self.snapshot() == before
        assert result["quest_updates"] == []
        assert not [e for e in self.events if e["type"] in REWARDS]

    async def private_quest(self, harness, condition, target):
        quest = f"arc_quest_{uuid4().hex}"
        stages = [
            {
                "objective": "Reach the condition",
                "target_location_id": target,
                "completion_conditions": condition,
                "on_complete": {"xp": 50},
            },
            {"objective": "Next", "completion_conditions": {"type": "decision_made"}},
        ]
        await self.pool.execute(
            "INSERT INTO quests(id,data) VALUES($1,$2::jsonb)", quest, json.dumps({"name": quest, "stages": stages})
        )

        async def cleanup():
            await self.pool.execute("DELETE FROM player_quests WHERE quest_id=$1", quest)
            await self.pool.execute("DELETE FROM quests WHERE id=$1", quest)

        harness.stack.callback(lambda: harness.run_sync(cleanup()))
        await self.quest_row(quest)
        return quest
