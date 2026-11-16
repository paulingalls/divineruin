"""Registered combat commands and durable quest receipts for First Blood."""

import json
from copy import deepcopy
from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock, patch

import asyncpg
from acceptance.greyvale_arc_walk_harness import QUEST, ArcWalk
from livekit.agents import AgentSession

import db_mutations
import db_queries
import event_types as E
from combat_agent import CombatAgent
from creation_rules import build_character_data
from exploration_agent import ExplorationAgent
from session_data import CompanionState


class FirstBloodWalk(ArcWalk):
    async def start(
        self,
        harness,
        route,
        *,
        encounter="hollow_patrol_greyvale",
        outcome="victory",
        stage=2,
        alive=True,
        cleared=True,
    ):
        harness.stack.enter_context(patch.object(ExplorationAgent, "_enter", new=AsyncMock()))
        harness.stack.enter_context(patch.object(CombatAgent, "_enter", new=AsyncMock()))
        await super().start(harness, "enter_mode", stage, agent=ExplorationAgent())
        self.route, self.outcome = route, outcome
        row = build_character_data(
            "First Blood", "human", "warrior", None, "", created_at=datetime(2026, 11, 1, tzinfo=UTC)
        )
        self.initial_xp = row["xp"] = 125
        await self.pool.execute("UPDATE players SET data=$2::jsonb WHERE player_id=$1", self.player, json.dumps(row))
        if not alive:
            self.sd.companion = CompanionState(id="companion_lira", name="Lira")
        self.sd.location_id = "greyvale_wilderness_north"
        await self.pool.execute(
            "UPDATE players SET data=jsonb_set(data,'{location_id}',to_jsonb($2::text)) WHERE player_id=$1",
            self.player,
            self.sd.location_id,
        )
        await self.command("enter_mode", {"mode": "combat", "encounter_id": encounter})
        state = self.sd.combat_state
        assert state is not None
        player = state.get_participant(self.player)
        assert player is not None
        player.hp_current = player.hp_max if alive else 0
        player.is_fallen = not alive
        player.is_dead = not alive
        enemies = [p for p in state.participants if p.type == "enemy"]
        for enemy in enemies:
            enemy.hp_current = 0
            enemy.is_fallen = True
        if not cleared or route == "resolve_phase":
            enemies[-1].hp_current = 1
            enemies[-1].is_fallen = False
        self.combat_xp = sum(e.xp_value for e in enemies)
        self.combat_id = state.combat_id
        if outcome == "deescalated":
            state.deescalated = True
        await db_mutations.save_combat_state(state.combat_id, state.to_dict())
        self.events.clear()
        return self

    async def command(self, name, args, *, error=False):
        self.model.commands.append((name, args))
        with self.sd._bind_authenticated_actor(self.player, 1, lambda *_: None):
            await self.session.run(user_input="Execute the next command.")
        receipt = list(self.model.receipts.values())[-1]
        assert receipt.name == name and receipt.is_error == error, receipt.output
        return receipt.output if error else json.loads(receipt.output)

    async def prepare(self):
        if self.route == "end_combat":
            return
        state = self.sd.combat_state
        assert state is not None
        player = state.get_participant(self.player)
        assert player is not None
        enemy = next(p for p in state.participants if p.type == "enemy" and not p.is_fallen)
        await self.command(
            "declare_phase",
            {
                "declarations": [
                    {
                        "kind": "attack",
                        "actor_id": self.player,
                        "action": player.action_pool[0]["name"],
                        "target_id": enemy.id,
                        "held_item_id": "",
                        "rider": "",
                    },
                    {"kind": "defend", "actor_id": enemy.id},
                ]
            },
        )
        result = await self.command("resolve_phase", {})
        assert self.sd.combat_state is not None and self.sd.combat_state.held_actions
        return result

    async def end(self):
        args = {"outcome": self.outcome} if self.route == "end_combat" else {}
        for _ in range(20):
            result = await self.command(self.route, args)
            if self.sd.combat_state is None:
                return result
        raise AssertionError("combat end did not drain")

    async def snapshot(self):
        tables = {
            "players": "player_id",
            "player_quests": "player_id",
            "player_inventory": "player_id",
            "npc_dispositions": "player_id",
        }
        rows = {}
        for table, key in tables.items():
            rows[table] = sorted(
                str(dict(row)) for row in await self.pool.fetch(f"SELECT * FROM {table} WHERE {key}=$1", self.player)
            )
        rows["combat"] = await self.pool.fetchval(
            "SELECT data FROM combat_instances WHERE combat_id=$1", self.combat_id
        )
        return (
            rows,
            deepcopy(self.sd.recent_events),
            self.sd.session_xp_earned,
            deepcopy(self.sd.session_quests_progressed),
            deepcopy(self.sd.player_summary_metrics),
            deepcopy(self.sd.session_items_found),
            deepcopy(self.events),
        )

    async def publish(self, raw, **kwargs):
        event = json.loads(raw)
        if event["type"] in {E.QUEST_UPDATED, E.WORLD_EVENT}:
            async with self.pool.acquire() as acquired:
                conn = cast(asyncpg.Connection, acquired)
                marker = await db_queries.get_player_quest(self.player, QUEST, conn=conn)
                assert marker is not None and marker["current_stage"] == 3
                player = await db_queries.get_player(self.player, conn=conn)
                assert player is not None and player["xp"] == self.initial_xp + self.combat_xp + 150
        self.events.append(event)

    async def rewarded(self, result):
        marker = await db_queries.get_player_quest(self.player, QUEST)
        assert marker is not None and marker["current_stage"] == 3
        player = await db_queries.get_player(self.player)
        assert player is not None
        assert player["xp"] == self.initial_xp + self.combat_xp + 150
        assert self.sd.session_xp_earned == player["xp"] - self.initial_xp
        updates = [e for e in self.events if e["type"] == E.QUEST_UPDATED]
        assert len(updates) == 1 and updates[0]["new_stage"] == 3
        xp = [e for e in self.events if e["type"] == E.XP_AWARDED]
        assert sorted(e["amount"] for e in xp) == sorted([150, self.combat_xp])
        assert sum(e["amount"] for e in xp) == player["xp"] - self.initial_xp
        inventory = await db_queries.get_player_inventory(self.player)
        bones = sum(i.get("quantity", 1) for i in inventory if i["id"] == "hollow_bone_fragment")
        assert bones == 1 + sum(i["quantity"] for i in result["loot"] if i["item_id"] == "hollow_bone_fragment")
        assert await db_queries.get_npc_disposition("elder_yanna", self.player) == "friendly"
        morale = [e for e in self.events if e["type"] == E.WORLD_EVENT and e["event_id"] == "millhaven_morale_change"]
        assert len(morale) == 1 and morale[0]["delta"] == 2
        quest = json.loads(await self.pool.fetchval("SELECT data FROM quests WHERE id=$1", QUEST))
        (update,) = result["quest_updates"]
        assert update["objective"] == quest["stages"][3]["objective"]
        assert update["narrative_beat"] == quest["stages"][2]["on_complete"]["narrative_beat"]
        assert {"type": "xp", "amount": 150, "leveled_up": True} in update["rewards_applied"]
        agent = self.session.current_agent
        assert isinstance(agent, ExplorationAgent)
        assert result["scene_transition"]["region"] == agent._agent_type == "dungeon"
        assert player["gold"] == 15 + result["currency_gold"]
        assert sum("morale shifted" in str(e) for e in self.sd.recent_events) == 1

    async def replay_refused(self):
        before = await self.snapshot()
        for command, args in [("end_combat", {"outcome": "victory"}), ("resolve_phase", {})]:
            # Exploration does not register combat commands; use the registered combat agent.
            await self.session.aclose()
            self.session = AgentSession(llm=self.model, userdata=self.sd)
            await self.session.start(CombatAgent())
            output = await self.command(command, args, error=True)
            assert "Not in combat" in output
        assert await self.snapshot() == before

    async def fresh_encounter(self):
        await self.session.aclose()
        self.session = AgentSession(llm=self.model, userdata=self.sd)
        await self.session.start(ExplorationAgent())
        before = await db_queries.get_player(self.player)
        assert before is not None
        self.events.clear()
        await self.command("enter_mode", {"mode": "combat", "encounter_id": "hollow_patrol_greyvale"})
        state = self.sd.combat_state
        assert state is not None
        for enemy in state.participants:
            if enemy.type == "enemy":
                enemy.hp_current = 0
                enemy.is_fallen = True
        await db_mutations.save_combat_state(state.combat_id, state.to_dict())
        result = await self.command("end_combat", {"outcome": "victory"})
        after = await db_queries.get_player(self.player)
        assert after is not None
        assert after["xp"] == before["xp"] + self.combat_xp
        assert result["quest_updates"] == []
        assert not [e for e in self.events if e["type"] in {E.QUEST_UPDATED, E.WORLD_EVENT}]
        assert await db_queries.get_npc_disposition("elder_yanna", self.player) == "friendly"
