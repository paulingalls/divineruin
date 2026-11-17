"""Continuous progression from the road through the journal and ruins victory."""

import json
import os
from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock, patch

import asyncpg
from acceptance.first_blood_walk import FirstBloodWalk
from acceptance.greyvale_arc_walk_harness import QUEST, ROAD, ArcWalk
from acceptance.journal_walk import PLACE
from sample_fixtures import CONTENT_ROOT

import db
import db_mutations
import db_queries
import event_types as E
from background_process import BackgroundProcess
from combat_agent import CombatAgent
from companion_profiles import get_companion_profile, select_companion_for_archetype
from companion_scaling import scale_companion_stats_to_player_level
from creation_rules import build_character_data
from exploration_agent import ExplorationAgent
from session_data import CompanionState


class RuinsFightWalk(FirstBloodWalk):
    async def start(self, harness, route):
        harness.stack.enter_context(patch.object(ExplorationAgent, "_enter", new=AsyncMock()))
        harness.stack.enter_context(patch.object(CombatAgent, "_enter", new=AsyncMock()))
        await ArcWalk.start(self, harness, "move_player", agent=ExplorationAgent())
        await (await db.get_redis()).delete(os.environ.get("CONTENT_CACHE_PREFIX", "") + "location:" + PLACE)
        row = build_character_data(
            "Road traveler", "human", "warrior", None, "", created_at=datetime(2026, 11, 1, tzinfo=UTC)
        )
        row["location_id"] = ROAD
        assert row["xp"] == 0 and row["level"] == 1
        await self.pool.execute("UPDATE players SET data=$2::jsonb WHERE player_id=$1", self.player, json.dumps(row))
        await db_mutations.add_inventory_item(self.player, "greyvale_veil_fragment", 1, tainted=False)
        companion = select_companion_for_archetype("warrior")
        self.sd.companion = CompanionState(id=companion, name=get_companion_profile(companion).name)
        self.route, self.outcome = route, "victory"
        self.bg = BackgroundProcess(self.session, self.sd)
        self.expected_reward = None
        return self

    async def publish(self, raw, **kwargs):
        event = json.loads(raw)
        if event["type"] in {E.QUEST_UPDATED, E.XP_AWARDED}:
            async with self.pool.acquire() as acquired:
                conn = cast(asyncpg.Connection, acquired)
                marker = await db_queries.get_player_quest(self.player, QUEST, conn=conn)
                player = await db_queries.get_player(self.player, conn=conn)
                assert marker is not None and player is not None
                if event["type"] == E.QUEST_UPDATED:
                    assert marker["current_stage"] == event["new_stage"]
                    if self.expected_reward:
                        assert marker["current_stage"] == 5 and marker.get("status", "active") == "active", marker
                        assert player["xp"] == self.expected_reward
                else:
                    # Combat and quest XP commit together; early receipts describe an intermediate total.
                    assert player["xp"] >= event["new_xp"]
        self.events.append(event)

    async def surfaced(self, encounter):
        from event_bus import GameEvent

        await self.bg._process_events([GameEvent(E.QUEST_UPDATED, {})], timed_out=False)
        instructions = self.session.current_agent.instructions
        assert isinstance(instructions, str)
        line = next(s for s in instructions.splitlines() if "  advance_quest:" in s)
        surfaced = line.split('encounter_id="', 1)[1].split('"', 1)[0]
        assert surfaced == encounter and "victory" in line
        await self.command("enter_mode", {"mode": "combat", "encounter_id": surfaced})
        state = self.sd.combat_state
        assert state is not None and state.encounter_id == encounter
        return state

    async def finish_setup(self, route):
        state = self.sd.combat_state
        assert state is not None
        enemies = [p for p in state.participants if p.type == "enemy"]
        for enemy in enemies:
            enemy.hp_current, enemy.is_fallen = 0, True
        if route == "resolve_phase":
            enemies[-1].hp_current, enemies[-1].is_fallen = 1, False
        self.combat_id = state.combat_id
        self.combat_xp = sum(e.xp_value for e in enemies)
        await db_mutations.save_combat_state(state.combat_id, state.to_dict())

    async def walk(self):
        await self.reward_road()
        await self.command("update_quest", {"quest_id": QUEST, "new_stage_id": 2})
        await self.arrive("greyvale_wilderness_north")
        await self.surfaced("hollow_patrol_greyvale")
        await self.finish_setup("end_combat")
        self.patrol_xp = self.combat_xp
        await self.command("end_combat", {"outcome": "victory"})
        for location in ("greyvale_ruins_exterior", PLACE):
            await self.arrive(location)
        result = await self.command(
            "check",
            {
                "roll": {
                    "kind": "discover",
                    "skill": "investigation",
                    "target": "research station",
                    "hearing_only": False,
                }
            },
        )
        assert result["quest_updates"][0]["new_stage"] == 4
        player = await db_queries.get_player(self.player)
        assert player is not None
        assert player["xp"] == 475 + self.patrol_xp and player["level"] == 3
        quest_xp = [e["amount"] for e in self.events if e["type"] == E.XP_AWARDED]
        assert sorted(quest_xp) == sorted([50, 75, 150, 200, self.patrol_xp]), quest_xp
        state = await self.surfaced("ruins_mawling_pair")
        marker = await db_queries.get_player_quest(self.player, QUEST)
        assert marker is not None
        assert marker["current_stage"] == 4
        participant = state.get_participant(self.player)
        assert participant is not None and participant.level == player["level"] == 3
        companion = self.sd.companion
        assert companion is not None
        ally = state.get_participant(companion.id)
        expected = scale_companion_stats_to_player_level(
            get_companion_profile(companion.id), participant.hp_max, player["level"]
        )
        assert ally is not None
        assert (ally.level, ally.hp_max, ally.ac, ally.attributes) == (
            expected.level,
            expected.hp,
            expected.ac,
            expected.attributes,
        )
        for table, identifier in [("encounter_templates", "ruins_mawling_pair"), ("creatures", "hollow_mawling_young")]:
            authored = next(
                r for r in json.loads((CONTENT_ROOT / f"content/{table}.json").read_text()) if r["id"] == identifier
            )
            seeded = json.loads(await self.pool.fetchval(f"SELECT data FROM {table} WHERE id=$1", identifier))
            assert seeded == authored
        await self.finish_setup(self.route)
        self.inventory_before = {
            r["id"]: r.get("quantity", 1) for r in await db_queries.get_player_inventory(self.player)
        }
        self.gold_before = player["gold"]
        self.initial_xp = player["xp"]
        self.expected_reward = self.initial_xp + self.combat_xp + 100
        self.events.clear()
        await self.prepare()

    async def reward_road(self):
        result = await self.arrive()
        assert result["quest_updates"][0]["new_stage"] == 1

    async def rewarded_ruins(self):
        result = await self.end()
        marker = await db_queries.get_player_quest(self.player, QUEST)
        assert marker is not None
        player = await db_queries.get_player(self.player)
        assert player is not None
        assert marker["current_stage"] == 5 and marker.get("status", "active") == "active", marker
        assert player["xp"] == 575 + self.patrol_xp + self.combat_xp
        assert self.sd.session_xp_earned == player["xp"]
        quest = json.loads(await self.pool.fetchval("SELECT data FROM quests WHERE id=$1", QUEST))
        (update,) = result["quest_updates"]
        assert update["narrative_beat"] == quest["stages"][4]["on_complete"]["narrative_beat"]
        assert update["objective"] == quest["stages"][5]["objective"]
        assert update["rewards_applied"] == [{"type": "xp", "amount": 100, "leveled_up": False}]
        updates = [e for e in self.events if e["type"] == E.QUEST_UPDATED]
        assert len(updates) == 1 and updates[0]["objective"] == update["objective"]
        assert sorted(e["amount"] for e in self.events if e["type"] == E.XP_AWARDED) == sorted([100, self.combat_xp])
        assert not [e for e in self.events if e["type"] in {E.WORLD_EVENT, E.DISPOSITION_CHANGED}]
        inventory = dict(self.inventory_before)
        for loot in result["loot"]:
            inventory[loot["item_id"]] = inventory.get(loot["item_id"], 0) + loot["quantity"]
        assert {r["id"]: r.get("quantity", 1) for r in await db_queries.get_player_inventory(self.player)} == inventory
        assert player["gold"] == self.gold_before + result["currency_gold"]
        assert isinstance(self.session.current_agent, ExplorationAgent)
        self.expected_reward = None
        assert player["class"] == "warrior" and player["level"] == 3
        assert not await db_queries.get_player_flag(self.player, "veythar_seal_mark.discovered")
        for item in ("greyvale_veil_fragment", "veythar_sealed_artifact"):
            held = [r for r in await db_queries.get_player_inventory(self.player) if r["id"] == item]
            assert held and held[0]["slot_info"].get("quantity", 1) > 0
        from event_bus import GameEvent

        await self.bg._process_events([GameEvent(E.QUEST_UPDATED, {})], timed_out=False)
        await self.arrive("greyvale_ruins_inner")
        assert "deeper → greyvale_ruins_inner" in self.bg._last_warm_layer
        assert self.sd.location_id == "greyvale_ruins_inner"
        arrived = await db_queries.get_player(self.player)
        artifact = await db_queries.get_inventory_item(self.player, "veythar_sealed_artifact")
        assert arrived is not None and arrived["location_id"] == "greyvale_ruins_inner"
        assert artifact is not None and artifact["quantity"] == 1
        await self.arrive(PLACE)
        await self.replay_refused()
        await self.repeat_victory()

    async def repeat_victory(self):
        from livekit.agents import AgentSession

        await self.session.aclose()
        self.session = AgentSession(llm=self.model, userdata=self.sd)
        await self.session.start(ExplorationAgent())
        self.events.clear()
        before = await db_queries.get_player(self.player)
        assert before is not None
        metrics = list(self.sd.session_quests_progressed)
        await self.command("enter_mode", {"mode": "combat", "encounter_id": "ruins_mawling_pair"})
        await self.finish_setup("end_combat")
        result = await self.command("end_combat", {"outcome": "victory"})
        after = await db_queries.get_player(self.player)
        assert after is not None
        assert after["xp"] == before["xp"] + self.combat_xp
        assert result["quest_updates"] == []
        assert self.sd.session_quests_progressed == metrics
        assert not [e for e in self.events if e["type"] == E.QUEST_UPDATED]
