"""Emris completion through registered commands and the real background consumer."""

import json
from unittest.mock import patch

from acceptance.greyvale_arc_walk_harness import QUEST
from acceptance.greyvale_finish_line import assert_finish
from acceptance.quest_decision_walk import command, decision_walk
from sample_fixtures import CONTENT_ROOT

import bg_event_handlers
import db_content_queries
import db_mutations
import db_queries
import db_session_queries
import event_types as E
from bg_speech import SpeechPriority
from event_bus import EventBus, GameEvent
from god_whisper_data import get_god_profile


async def set_patron(arc, patron):
    arc.sd.party.primary.patron_id = patron
    await arc.pool.execute(
        "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1",
        arc.player,
        json.dumps({"divine_favor": {"patron": patron, "level": 10, "max": 100, "last_whisper_level": 10}}),
    )


async def setup(harness, patron, location):
    arc = await decision_walk(harness)
    assert not (await command(arc, 7, "show_companion")).is_error
    arc.sd.location_id = location
    arc.sd.world_time = "night" if location == "emris_study" else "afternoon"
    await arc.pool.execute(
        "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1",
        arc.player,
        json.dumps({"location_id": location}),
    )
    await set_patron(arc, patron)
    await db_mutations.set_npc_disposition("scholar_emris", arc.player, "hostile", "setup")
    arc.sd.event_bus = EventBus()
    await arc.bg._process_events([GameEvent(E.QUEST_UPDATED, {})], timed_out=False)
    quest = await db_content_queries.get_quest(QUEST)
    assert quest is not None
    line = next(s for s in arc.bg._last_warm_layer.splitlines() if "  advance_quest:" in s)
    assert_finish(line, quest, 7)
    npcs = await db_queries.get_npcs_at_location(location)
    assert "scholar_emris" in [n["id"] for n in npcs]
    return arc


async def durable(arc):
    marker = await db_queries.get_player_quest(arc.player, QUEST)
    assert marker is not None
    return (
        await arc.pool.fetchval("SELECT data::text FROM players WHERE player_id=$1", arc.player),
        marker,
        await db_queries.get_npc_disposition("scholar_emris", arc.player),
        await db_queries.get_player_faction_reputation(arc.player, "accord_guild"),
    )


async def completed(arc):
    patron = arc.sd.party.primary.patron_id
    before = await durable(arc)
    arc.bg._speech_queue.clear()
    arc.sd.event_bus.drain()
    receipt = await command(arc, 8)
    assert not receipt.is_error, receipt.output
    response = json.loads(receipt.output)
    after = await durable(arc)
    player = json.loads(after[0])
    assert player["xp"] == json.loads(before[0])["xp"] + 200
    assert player["divine_favor"]["level"] == (10 if patron == "none" else 15)
    assert after[1]["current_stage"] == 8 and after[1]["status"] == "completed"
    assert after[1]["decisions"] == {"artifact_choice": "show_companion"}
    assert after[2] == "trusted" and after[3] == (before[3] or 0) + 5
    assert response["completed"] and response["objective"] == ""
    assert await db_queries.get_inventory_item(arc.player, "veythar_sealed_artifact") is not None
    events = arc.sd.event_bus.drain()
    assert (
        len(
            [
                e
                for e in events
                if e.event_type == E.WORLD_EVENT and e.payload["event_id"] == "god_whisper:player_patron"
            ]
        )
        == 1
    )
    with patch("bg_event_handlers.get_god_profile", wraps=bg_event_handlers.get_god_profile) as lookup:
        await arc.bg._process_events(events, timed_out=False)
        whispers = [s for s in arc.bg._speech_queue if s.priority == SpeechPriority.CRITICAL]
        if patron == "none":
            lookup.assert_not_called()
            assert not whispers
        else:
            lookup.assert_called_once_with(patron)
            (whisper,) = whispers
            profile = get_god_profile(patron)
            assert f"[{profile.voice_character}, {profile.voice_emotion}]" in whisper.instructions
            assert whisper.stinger_sound == profile.stinger_sound and whisper.recipient_id == arc.player
    authored = next(
        s for s in json.loads((CONTENT_ROOT / "content/scenes.json").read_text()) if s["id"] == "scene_return_to_accord"
    )
    seeded = json.loads(await arc.pool.fetchval("SELECT data FROM scenes WHERE id=$1", authored["id"]))
    assert seeded == authored
    assert response["narrative_beat"] == seeded["aftermath"] and seeded["aftermath"]
    assert not [q for q in await db_queries.get_active_player_quests(arc.player) if q["quest_id"] == QUEST]
    assert not arc.bg._quest_cache
    assert "advance_quest:" not in arc.bg._last_warm_layer
    assert not (await db_session_queries.get_session_init_payload(arc.player))["quests"]
    channels = (list(arc.events), list(arc.bg._speech_queue))
    assert (await command(arc, 8)).is_error
    assert await durable(arc) == after
    assert (arc.events, arc.bg._speech_queue) == channels and arc.sd.event_bus.qsize == 0


async def close_walk(arc, harness):
    from acceptance.quest_decision_walk import assert_choice
    from acceptance.voice_condition_harness import ScenarioModel
    from livekit.agents import AgentSession

    from background_process import BackgroundProcess
    from exploration_agent import ExplorationAgent
    from session_data import SessionData

    arc.quest = QUEST
    quest = await db_content_queries.get_quest(QUEST)
    assert quest is not None
    authored = next(q for q in json.loads((CONTENT_ROOT / "content/quests.json").read_text()) if q["id"] == QUEST)
    assert quest == authored and len(quest["stages"]) == 8
    ledger = set()
    assert await db_queries.get_npc_disposition("guildmaster_torin", arc.player) == "friendly"
    ledger.add("torin_disposition +1")
    assert await db_queries.get_npc_disposition("elder_yanna", arc.player) == "friendly"
    ledger.add("yanna_disposition +2")
    assert not (await command(arc, 7, "show_companion")).is_error
    row = await db_queries.get_player(arc.player)
    assert row is not None
    assert row["flags"]["companion_knows_artifact"] is True
    assert await db_queries.get_npc_disposition(arc.sd.companion.id, arc.player) == "trusted"
    ledger.update({"set_flag:companion_knows_artifact:true", "companion_disposition +3"})
    marker = await db_queries.get_player_quest(arc.player, QUEST)
    before = await durable(arc)
    companion, room = arc.sd.companion, arc.sd.room
    await arc.session.aclose()
    arc.sd = SessionData(player_id=arc.player, location_id=row["location_id"], room=room)
    arc.sd.companion = companion
    arc.sd.party.primary.patron_id = row["divine_favor"]["patron"]
    arc.sd.event_bus = EventBus()
    arc.model = ScenarioModel([])
    arc.session = AgentSession(llm=arc.model, userdata=arc.sd)
    await arc.session.start(ExplorationAgent())
    harness.stack.callback(lambda: harness.run_sync(arc.session.aclose()))
    arc.bg = BackgroundProcess(arc.session, arc.sd)
    with patch("bg_event_handlers.get_god_profile", wraps=bg_event_handlers.get_god_profile) as lookup:
        await arc.bg._process_events([GameEvent(E.QUEST_UPDATED, {})], timed_out=False)
        lookup.assert_not_called()
    assert await durable(arc) == before
    assert not [s for s in arc.bg._speech_queue if s.priority == SpeechPriority.CRITICAL]
    assert await db_queries.get_player_quest(arc.player, QUEST) == marker
    scene = json.loads(await arc.pool.fetchval("SELECT data FROM scenes WHERE id='scene_return_to_accord'"))
    assert scene["instructions"] in arc.bg._last_warm_layer
    assert "tablet" in scene["instructions"] and "new_stage_id=8" in arc.bg._last_warm_layer
    for location in (
        "greyvale_ruins_exterior",
        "greyvale_wilderness_north",
        "millhaven",
        "greyvale_south_road",
        "accord_market_square",
        "accord_dockside",
    ):
        await arc.arrive(location)
    await completed(arc)
    ledger.update(
        {"emris_disposition +4", "accord_guild_reputation completed_faction_quest", "event:god_whisper:player_patron"}
    )
    player = await db_queries.get_player(arc.player)
    assert player is not None
    assert player["xp"] == 775 + arc.patrol_xp + 2 * arc.combat_xp
    other = await decision_walk(harness)
    await assert_choice(other, "keep_artifact")
    ledger.add("set_flag:player_has_veythar_artifact:true")
    declared = {effect for s in quest["stages"] for effect in s.get("on_complete", {}).get("world_effects", [])}
    declared.update(
        effect for o in quest["stages"][6]["completion_conditions"]["options"].values() for effect in o["effects"]
    )
    assert ledger == declared, (declared - ledger, ledger - declared)
