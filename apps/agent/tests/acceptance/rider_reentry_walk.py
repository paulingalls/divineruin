"""Persisted re-entry, reconnect and terminal defeat in a real room."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import patch

from acceptance._capstone_helpers import _d20
from acceptance.first_episode_harness import episode, until
from acceptance.rider_walk import requested
from livekit.agents import llm

import db
import db_content_queries
import db_mutations
import db_mutations_companion
import db_mutations_death
import db_queries
from creation_rules import build_character_data
from exploration_agent import ExplorationAgent


async def saved_rider(player_id):
    row = build_character_data("Vale", "human", "warrior", "kaelen", "", created_at=datetime.now(UTC))
    row.update(
        location_id="accord_market_square",
        flags={"onboarding_beat": "complete", "first_episode": "rider", "companion_met": True},
    )
    await db_mutations.create_player(player_id, None, row)
    await db_mutations_companion.upsert_companion_relationship(
        player_id, "companion_lira", relationship_tier=1, session_count=1, affinity=0, session_memories=[]
    )


async def reenter(run):
    sd = run.session.userdata
    await until(lambda: run.session.current_speech is None and not sd.background._speech_queue)
    agent = ExplorationAgent(initial_location=sd.location_id)
    run.session.update_agent(agent)
    await until(lambda: run.session.current_agent is agent)
    await asyncio.sleep(0.1)


async def reentry_and_defeat(server, tmp_path):
    async with episode(server, tmp_path, prepare=saved_rider, initial_agent="ExplorationAgent", preserve=True) as run:
        pid = run.player_id
        await run.reconnect()
        await reenter(run)
        assert not any("fragment_shadeling" in text for _, text in run.speeches)
    async with episode(server, tmp_path, player_id=pid, initial_agent="ExplorationAgent") as run:
        sd = run.session.userdata
        assert await db_queries.get_player_flag_value(pid, "first_episode") == "rider"
        scene = await db_content_queries.get_scene("scene_rider_arrival")
        assert scene is not None
        instructions = scene["instructions"]
        receipt = await run.turn("query_info", kind="location", target_id=sd.location_id)
        assert not receipt.is_error, receipt.output
        assert requested(run, instructions)
        for destination in ("accord_guild_hall", "accord_market_square"):
            receipt = await run.turn("move_player", destination_id=destination)
            assert not receipt.is_error, receipt.output
        pool = await db.get_pool()
        for receipt, onboarding, active_quest in (
            ("complete", "complete", False),
            (None, "complete", True),
            (None, 2, False),
        ):
            await pool.execute("UPDATE players SET data=data #- '{flags,first_episode}' WHERE player_id=$1", pid)
            if receipt is not None:
                await db_mutations.set_player_flag(pid, "first_episode", receipt)
            await db_mutations.set_player_flag(pid, "onboarding_beat", onboarding)
            if active_quest:
                await db_mutations.set_player_quest(pid, "greyvale_anomaly", {"current_stage": 0, "status": "active"})
            else:
                await pool.execute("DELETE FROM player_quests WHERE player_id=$1", pid)
            await reenter(run)
            assert await db_queries.get_player_flag_value(pid, "first_episode") == receipt
        assert not any("fragment_shadeling" in text for _, text in run.speeches)
        await db_mutations.set_player_flag(pid, "onboarding_beat", "complete")
        await db_mutations.set_player_flag(pid, "first_episode", "rider")
        for destination in ("accord_guild_hall", "accord_guild_infirmary"):
            result = await run.turn("move_player", destination_id=destination)
            assert not result.is_error, result.output
        run.requests.clear()
        receipt = await run.turn("query_info", kind="location", target_id=sd.location_id)
        assert not receipt.is_error, receipt.output
        assert requested(run, instructions)
        receipt = await run.turn("enter_mode", mode="combat", encounter_id="fragment_shadeling")
        assert not receipt.is_error, receipt.output
        await until(lambda: run.session.current_agent.__class__.__name__ == "CombatAgent")
        cs = sd.combat_state
        assert cs is not None
        for actor in cs.participants:
            if actor.type != "enemy":
                actor.hp_current = 0
                actor.is_fallen = True
        player_actor = cs.get_participant(pid)
        assert player_actor is not None
        player_actor.death_save_failures = 2
        with patch("combat_resolution.dice_roll", return_value=_d20(1)):
            receipt = await run.turn("request_death_save", player_id=pid)
        assert not receipt.is_error, receipt.output
        enemy = next(p for p in cs.participants if p.type == "enemy")
        receipt = await run.turn(
            "declare_phase", declarations=[{"reshape": [], "kind": "defend", "actor_id": enemy.id}]
        )
        assert not receipt.is_error, receipt.output
        for _ in range(8):
            receipt = await run.turn("resolve_phase")
            assert not receipt.is_error, receipt.output
            if sd.combat_state is None:
                break
        assert sd.combat_state is None
        await until(lambda: run.session.current_agent.__class__.__name__ == "ExplorationAgent")
        saved = await db_queries.get_player(pid)
        assert saved is not None
        assert saved["hp"]["current"] > 0 and saved["location_id"] == sd.location_id
        assert (await db_mutations_death.read_death_history(pid))["count"] == 1
        assert saved["flags"]["first_episode"] == "complete"
        quest = await db_queries.get_player_quest(pid, "greyvale_anomaly")
        assert quest is not None
        assert quest["current_stage"] == 0
        fragments = [i for i in await db_queries.get_player_inventory(pid) if i["id"] == "greyvale_veil_fragment"]
        assert len(fragments) == 1 and fragments[0]["slot_info"]["quantity"] == 1
        background = sd.background
        assert background is not None
        await until(lambda: background._episode == "complete")
        assert background._task is not None and not background._task.done()
        summary = " ".join(
            item.text_content or ""
            for item in run.session.current_agent.chat_ctx.items
            if isinstance(item, llm.ChatMessage)
        )
        assert "Combat resolved: defeat." in summary
        assert scene["aftermath"] in summary
        run.requests.clear()
        receipt = await run.turn("query_info", kind="inventory")
        assert not receipt.is_error, receipt.output
        assert requested(run, scene["aftermath"])
