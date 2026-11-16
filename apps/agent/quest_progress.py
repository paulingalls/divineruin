"""Engine-driven quest conditions reached by arriving at a location."""

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
