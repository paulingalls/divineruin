"""Room-level observations for the rider, hints and first combat handoff."""

import time

from acceptance.first_episode_harness import until

import db_content_queries
import db_queries
import event_types as E
from bg_speech import SpeechPriority
from event_bus import GameEvent


def requested(run, text):
    return any(
        text in (item.text_content or "")
        for request in run.requests
        for item in request["chat_ctx"].items
        if hasattr(item, "text_content")
    )


async def silence(run, hint):
    sd = run.session.userdata
    sd.last_player_speech_time = sd.last_agent_speech_end = time.time() - 120
    sd.background._scene_hint_state["last_hint_time"] = 0
    sd.event_bus.publish(GameEvent(event_type=E.LOCATION_CHANGED, payload={"location_id": sd.location_id}))
    await until(lambda: requested(run, hint))


async def finish_first_episode(run):
    sd = run.session.userdata
    scene = await db_content_queries.get_scene("scene_rider_arrival")
    assert scene is not None
    instructions = scene["instructions"]
    await until(lambda: any(text == instructions for _, text in run.speeches))
    assert [(priority, text) for priority, text in run.speeches if text == instructions] == [
        (SpeechPriority.CRITICAL, instructions)
    ]
    await until(lambda: requested(run, instructions))
    assert await db_queries.get_player_flag_value(run.player_id, "first_episode") == "rider"
    await silence(run, scene["beats"][0]["companion_hints"][0])
    for destination in ("accord_guild_hall", "accord_guild_infirmary", "accord_guild_hall", "accord_guild_infirmary"):
        result = await run.turn("move_player", destination_id=destination)
        assert not result.is_error, result.output
        saved = await db_queries.get_player(run.player_id)
        assert saved is not None and saved["location_id"] == destination
    await silence(run, scene["beats"][0]["companion_hints"][1])
    receipt = await run.turn("enter_mode", mode="combat", encounter_id="fragment_shadeling")
    assert not receipt.is_error, receipt.output
    await until(lambda: run.session.current_agent.__class__.__name__ == "CombatAgent")
    cs = sd.combat_state
    assert cs is not None
    assert cs.location_id == "accord_guild_infirmary"
    enemies = [p for p in cs.participants if p.type == "enemy"]
    assert len(enemies) == 1 and enemies[0].role == "standard"
    enemies[0].hp_current = 0
    enemies[0].is_fallen = True
    receipt = await run.turn("end_combat", outcome="victory")
    assert not receipt.is_error, receipt.output
    await until(lambda: run.session.current_agent.__class__.__name__ == "ExplorationAgent")
    player = await db_queries.get_player(run.player_id)
    assert player is not None
    assert player["flags"]["first_episode"] == "complete"
    quest = await db_queries.get_player_quest(run.player_id, "greyvale_anomaly")
    assert quest is not None
    assert (quest.get("status", "active"), quest["current_stage"]) == ("active", 0)
    assert player["xp"] < 75 and sd.session_xp_earned < 75 and player["level"] == 1
    inventory = await db_queries.get_player_inventory(run.player_id)
    fragments = [r for r in inventory if r["id"] == "greyvale_veil_fragment"]
    assert len(fragments) == 1 and fragments[0]["slot_info"]["quantity"] == 1
    await until(
        lambda: (
            run.packets(E.QUEST_UPDATED)
            and any(p["item_id"] == "greyvale_veil_fragment" for p in run.packets(E.ITEM_ACQUIRED))
        )
    )
    assert sum(text == instructions for _, text in run.speeches) == 1
    await until(lambda: sd.background._episode == "complete")
    assert sd.background._task is not None and not sd.background._task.done()
    print(f"first episode total XP={player['xp']}; session XP={sd.session_xp_earned}")
