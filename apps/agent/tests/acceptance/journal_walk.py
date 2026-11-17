"""Journal commands and committed-state observations at the agent boundary."""

import json
from typing import cast
from unittest.mock import patch

import asyncpg
from acceptance._capstone_helpers import _d20
from acceptance.greyvale_arc_walk_harness import QUEST, ArcWalk
from acceptance.seeds import seed_player

import db
import db_content_queries
import db_mutations
import db_queries
import event_types as E

ITEM = "ruins_journal_fragment"
PLACE = "greyvale_ruins_entrance"


class JournalWalk(ArcWalk):
    async def start(self, harness, stage: int | None = 3):
        harness.stack.enter_context(patch("check_resolution.dice_roll", side_effect=lambda *_, **__: _d20(20)))
        await super().start(harness, "check", stage)
        self.sd.location_id = PLACE
        await self.pool.execute(
            "UPDATE players SET data=jsonb_set(data,'{location_id}',to_jsonb($2::text)) WHERE player_id=$1",
            self.player,
            PLACE,
        )
        self.guest = self.player + "_guest"
        await seed_player(self.pool, player_id=self.guest, class_="warrior", location_id=PLACE)
        return self

    def add_guest(self):
        from party_state import PartyState

        if not self.sd.party.contains(self.guest):
            self.sd.party.members.append(PartyState.solo(self.guest).primary)

    async def command(self, name, args, *, actor=None, error=False):
        if actor == self.guest:
            self.add_guest()
        self.model.commands.append((name, args))
        with self.sd._bind_authenticated_actor(actor or self.player, 1, lambda *_: None):
            await self.session.run(user_input="Execute the next command.")
        receipt = list(self.model.receipts.values())[-1]
        assert receipt.name == name and receipt.is_error == error, receipt.output
        return receipt.output if error else json.loads(receipt.output)

    async def discover(self, *, actor=None, error=False, skill="investigation", target="research station"):
        return await self.command(
            "check",
            {"roll": {"kind": "discover", "skill": skill, "target": target, "hearing_only": False}},
            actor=actor,
            error=error,
        )

    async def quantity(self, item=ITEM, *, actor=None, conn=None):
        row = await db_queries.get_inventory_item(actor or self.player, item, conn=conn)
        return row["quantity"] if row else 0

    async def marker(self, quest=QUEST, *, conn=None):
        row = await db_queries.get_player_quest(self.player, quest, conn=conn)
        return row["current_stage"] if row else -1

    async def durable(self):
        return [
            [dict(r) for r in await self.pool.fetch(sql, self.player, self.guest)]
            for sql in [
                "SELECT * FROM players WHERE player_id IN ($1,$2) ORDER BY player_id",
                "SELECT * FROM player_inventory WHERE player_id IN ($1,$2) ORDER BY player_id,item_id,tainted",
                "SELECT * FROM player_quests WHERE player_id IN ($1,$2) ORDER BY player_id,quest_id",
            ]
        ]

    async def publish(self, raw, **kwargs):
        event = json.loads(raw)
        async with self.pool.acquire() as acquired:
            conn = cast(asyncpg.Connection, acquired)
            if event["type"] == E.INVENTORY_UPDATED:
                assert {k: event[k] for k in ("player_id", "inventory_revision", "inventory")} == (
                    await db_queries.get_inventory_snapshot(event["player_id"], conn=conn)
                )
            if event["type"] == E.QUEST_UPDATED:
                assert await self.marker(event["quest_id"], conn=conn) == event["new_stage"]
            if event["type"] in {E.QUEST_UPDATED, E.INVENTORY_UPDATED, E.XP_AWARDED}:
                self.observed = await db_queries.get_player(self.player, conn=conn)
        self.events.append(event)

    async def rewarded(self, result):
        assert await self.quantity() == 1
        player = await db_queries.get_player(self.player)
        assert player is not None
        assert player["flags"][ITEM + ".discovered"] is True
        assert player["xp"] == 200
        assert self.sd.corruption_level == 1
        assert (
            len([e for e in self.events if e["type"] == E.WORLD_EVENT and e["event_id"] == "ruins_discovery_ripple"])
            == 1
        )
        assert await self.marker() == 4
        assert await self.quantity("veythar_sealed_artifact") == 0
        quest = await db_content_queries.get_quest(QUEST)
        assert quest is not None
        assert self.observed is not None
        (update,) = result["quest_updates"]
        assert update["narrative_beat"] == quest["stages"][3]["on_complete"]["narrative_beat"]
        assert update["objective"] == quest["stages"][4]["objective"]
        assert self.observed["flags"][ITEM + ".discovered"]
        assert len([e for e in self.events if e["type"] == E.QUEST_UPDATED]) == 1

    async def private_items(self, harness, *, items=None, chained=False):
        condition = {"type": "item_discovered", "items": items or [ITEM], "location": PLACE}
        quest = await self.private_quest(harness, condition, PLACE)
        if chained:
            data = await db_content_queries.get_quest(quest)
            assert data is not None
            data["stages"][0]["on_complete"]["world_effects"] = ["greyvale_corruption +1"]
            data["stages"].insert(
                1, {**data["stages"][0], "on_complete": {"xp": 60, "world_effects": ["greyvale_corruption +1"]}}
            )
            await self.pool.execute("UPDATE quests SET data=$2::jsonb WHERE id=$1", quest, json.dumps(data))
            await self.pool.execute("DELETE FROM player_quests WHERE quest_id=$1", quest)
            await (await db.get_redis()).delete("quest:" + quest)
        return quest

    async def remove_journal(self):
        await self.pool.execute("DELETE FROM player_inventory WHERE player_id=$1 AND item_id=$2", self.player, ITEM)

    async def hold(self, item, *, actor=None):
        actor = actor or self.player
        await db_mutations.set_player_flag(actor, item + ".discovered", True)
        await db_mutations.add_inventory_item(actor, item, 1, tainted=False)
