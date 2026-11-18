"""Registered gift commands with real durable rows and deterministic dice."""

import json
from unittest.mock import patch

from acceptance._capstone_helpers import _d20
from acceptance.journal_walk import JournalWalk
from acceptance.voice_condition_harness import ScenarioModel
from livekit.agents import Agent, AgentSession
from sample_fixtures import make_mock_room

import db_queries
from exploration_agent import EXPLORATION_TOOLS
from session_data import SessionData

GIFT = "veythar_lorekeepers_insight"
CALL = f'activate(id="{GIFT}")'


def favor(patron: str) -> dict:
    """A follower's divine_favor in the shape character creation writes (level and max always present)."""
    return {"patron": patron, "level": 0, "max": 100, "last_whisper_level": 0}


class GiftWalk(JournalWalk):
    async def start(self, harness, stage=3):
        await super().start(harness, stage)
        await self.patch(divine_favor=favor("veythar"), keepsake="unchanged", patron_gifts={"other": {"x": 1}})
        await self.connect(harness)
        return self

    async def connect(self, harness):
        if hasattr(self, "session"):
            await self.session.aclose()
        row = await self.row()
        room = make_mock_room()
        room.local_participant.publish_data.side_effect = self.publish
        self.sd = SessionData(player_id=self.player, location_id=row["location_id"], room=room)
        self.validator = lambda *_: None
        self.reroll_in_flight = False
        self.model = ScenarioModel([])
        tools = [t for t in EXPLORATION_TOOLS if t.__name__ in {"check", "activate", "rest"}]
        self.session = AgentSession(llm=self.model, userdata=self.sd)
        await self.session.start(Agent(instructions="Execute the command.", tools=tools))
        session = self.session
        harness.stack.callback(lambda: harness.run_sync(session.aclose()))

    async def patch(self, **data):
        await self.pool.execute(
            "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1", self.player, json.dumps(data)
        )

    async def command(self, name, args, *, actor=None, error: bool | None = False):
        self.model.commands.append((name, args))
        self.reroll_in_flight = name == "activate"
        try:
            with self.sd._bind_authenticated_actor(actor or self.player, 1, lambda *_: None):
                await self.session.run(user_input="Execute the next command.")
        finally:
            self.reroll_in_flight = False
        receipt = list(self.model.receipts.values())[-1]
        assert receipt.name == name, receipt.output
        if error is not None:
            assert receipt.is_error == error, receipt.output
        return receipt.output if receipt.is_error else json.loads(receipt.output)

    async def publish(self, raw, **kwargs):
        if self.reroll_in_flight:
            assert await self.state() == {"spent": True, "pending": None}
        await super().publish(raw, **kwargs)

    async def row(self):
        row = await db_queries.get_player(self.player)
        assert row is not None
        return row

    async def state(self):
        return (await self.row()).get("patron_gifts", {}).get(GIFT)

    async def skill(self, skill="arcana", face=2, difficulty="hard"):
        with patch("check_resolution.dice_roll", return_value=_d20(face)) as rolls:
            result = await self.command(
                "check",
                {
                    "roll": {
                        "kind": "skill",
                        "skill": skill,
                        "difficulty": difficulty,
                        "context_description": "Remember the old lore",
                        "hearing_only": False,
                    }
                },
            )
        assert rolls.call_count == 1
        return result

    async def search(self, face=2, **kwargs):
        with patch("check_resolution.dice_roll", return_value=_d20(face)) as rolls:
            result = await self.discover(**kwargs)
        assert rolls.call_count == 1
        return result

    async def use(self, face=20, *, error=False):
        with patch("check_resolution.dice_roll", return_value=_d20(face)) as rolls:
            result = await self.command("activate", {"id": GIFT}, error=error)
        assert rolls.call_count == (0 if error else 1)
        return result
