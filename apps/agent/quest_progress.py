"""Engine-driven quest conditions reached by arrival and combat completion."""

import json

from livekit.agents.voice import RunContext

import db
import db_content_queries
import db_mutations
import db_queries
from quest_tools import _update_quest_impl
from session_data import SessionData


async def advance_on_arrival(
    context: RunContext[SessionData],
    destination_id: str,
    *,
    db_mod=db,
    mutations=db_mutations,
    queries=db_queries,
    content=db_content_queries,
) -> list[dict]:
    updates = []
    for quest in await queries.get_active_player_quests(context.userdata.primary_player_id):
        stage = quest["current_stage"]
        condition = quest["stages"][stage].get("completion_conditions", {})
        if condition.get("type") != "location_reached" or condition.get("location") != destination_id:
            continue
        result = await _update_quest_impl(
            context,
            quest["quest_id"],
            stage + 1,
            db_mod=db_mod,
            mutations=mutations,
            queries=queries,
            content=content,
        )
        updates.append(json.loads(result))
    return updates


async def advance_on_combat_end(
    session, state, outcome, *, conn, sink, queries=db_queries, mutations=db_mutations, content=db_content_queries
):
    import event_types as E
    from combat_down import is_terminally_down
    from inventory_refresh import inventory_payload
    from quest_authority import advance_quest_db

    enemies = [p for p in state.participants if p.type == "enemy"]
    if outcome != "victory" or not enemies or any(not p.is_fallen for p in enemies):
        return []
    if not any(p.type == "player" and not is_terminally_down(p) for p in state.participants):
        return []
    pending = []
    for quest in await queries.get_active_player_quests(session.primary_player_id, conn=conn):
        stage = quest["current_stage"]
        condition = quest["stages"][stage].get("completion_conditions", {})
        if (condition.get("type"), condition.get("encounter"), condition.get("outcome")) != (
            "combat_completed",
            state.encounter_id,
            "victory",
        ):
            continue
        advance = await advance_quest_db(
            session, quest["quest_id"], stage + 1, conn=conn, mutations=mutations, queries=queries, content=content
        )
        for event_type, payload in advance.events:
            await sink.emit(session.room, event_type, payload, event_bus=session.event_bus)
        for pid in sorted({pid for pid, _ in advance.item_recipients}):
            await sink.emit(
                session.room,
                E.INVENTORY_UPDATED,
                await inventory_payload(pid, queries=queries, conn=conn),
                event_bus=session.event_bus,
            )
        pending.append(advance)
    return pending


def finish_combat_quests(session, end_data, response, summary_parts):
    from quest_completion import finish_quest

    updates = [finish_quest(session, pending) for pending in end_data["quest_updates"]]
    response["quest_updates"] = updates
    for update in updates:
        summary_parts.append(json.dumps(update))
        if transition := update.get("scene_transition"):
            session.pre_combat_agent_type = transition["region"]
            response["scene_transition"] = transition
