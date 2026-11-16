"""The persisted rider receipt owns first-episode entry, hints and settlement."""

import db
import db_content_queries
import db_mutations
import db_queries
import event_types as E
from bg_speech import SpeechPriority
from combat_events import EventSink
from inventory_refresh import inventory_payload
from onboarding_tools import ONBOARDING_COMPLETE
from quest_authority import PendingQuest, advance_quest_db
from quest_completion import finish_quest
from session_data import CombatState, SessionData
from tool_support import build_item_acquired_payload

SCENE = "scene_rider_arrival"
ENCOUNTER = "fragment_shadeling"
INFIRMARY = "accord_guild_infirmary"
FRAGMENT = "greyvale_veil_fragment"
QUEST = "greyvale_anomaly"


async def enter(session: SessionData) -> None:
    if session.location_id != "accord_market_square":
        return
    pid = session.primary_player_id
    async with db.transaction() as conn:
        player = await db_queries.get_player(pid, conn=conn, for_update=True)
        if player is None:
            raise RuntimeError(f"First episode player {pid!r} is missing")
        flags = player.get("flags", {})
        if flags.get("onboarding_beat") != ONBOARDING_COMPLETE or "first_episode" in flags:
            return
        if await db_queries.get_active_player_quests(pid, conn=conn):
            return
        scene = await db_content_queries.get_scene(SCENE)
        if not scene or not scene.get("instructions", "").strip():
            raise RuntimeError("The rider scene has no usable instructions")
        await db_mutations.set_player_flag(pid, "first_episode", "rider", conn=conn)
    assert session.background is not None
    session.background._queue_speech(SpeechPriority.CRITICAL, scene["instructions"])


def hint_scene(scene_cache: dict[str, dict], episode, location_id: str) -> dict | None:
    if episode == "rider" and location_id in ("accord_market_square", INFIRMARY):
        return scene_cache.get(SCENE)
    return None


async def settle(session: SessionData, cs: CombatState, *, conn, sink: EventSink) -> PendingQuest | bool | None:
    if cs.encounter_id != ENCOUNTER or cs.location_id != INFIRMARY:
        return None
    pid = session.primary_player_id
    # Different sessions can finish different combat rows for the same saved episode.
    await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", f"first_episode:{pid}")
    if await db_queries.get_player_flag_value(pid, "first_episode", conn=conn) != "rider":
        return None
    pending = None
    if await db_queries.get_player_quest(pid, QUEST, conn=conn) is None:
        pending = await advance_quest_db(session, QUEST, 0, conn=conn)
        for event_type, payload in pending.events:
            await sink.emit(session.room, event_type, payload, event_bus=session.event_bus)
    item = await db_content_queries.get_item(FRAGMENT)
    if item is None:
        raise RuntimeError("The first episode fragment is missing")
    await db_mutations.add_inventory_item(pid, FRAGMENT, 1, tainted=False, conn=conn)
    await db_mutations.set_player_flag(pid, "first_episode", "complete", conn=conn)
    await sink.emit(
        session.room,
        E.ITEM_ACQUIRED,
        build_item_acquired_payload(
            item,
            item_id=FRAGMENT,
            quantity=1,
            source="first_episode",
            player_id=pid,
        ),
        event_bus=session.event_bus,
    )
    await sink.emit(
        session.room, E.INVENTORY_UPDATED, await inventory_payload(pid, conn=conn), event_bus=session.event_bus
    )
    return pending if pending is not None else True


def finish(session: SessionData, pending: PendingQuest | bool | None) -> dict | None:
    if pending is None:
        return None
    quest = finish_quest(session, pending) if isinstance(pending, PendingQuest) else None
    session.record_item_found(session.primary_player_id, "Veil Fragment")
    return {"item_id": FRAGMENT, "quest": quest, "first_episode": "complete"}
