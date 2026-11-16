"""Quest progression through the shared transactional reward authority."""

import json

from livekit.agents.llm import function_tool
from livekit.agents.voice import RunContext

import db
import db_activity_queries
import db_content_queries
import db_mutations
import db_mutations_divine
import db_queries
import milestones
from db_errors import db_tool
from game_events import publish_game_event
from inventory_refresh import publish_inventory
from quest_authority import _is_unpaid_for_stage as _is_unpaid_for_stage
from quest_authority import advance_quest_db
from quest_completion import finish_quest
from quest_world_effects import _apply_world_effects as _apply_world_effects
from session_data import SessionData


@function_tool()
@db_tool
async def update_quest(
    context: RunContext[SessionData],
    quest_id: str,
    new_stage_id: int,
) -> str:
    """Advance a quest to a new stage. For starting a quest, use stage 0.
    Stages must advance forward — no skipping or going backward.
    Rewards from the completing stage are automatically applied.

    To COMPLETE a quest, advance it one past its last stage: pass new_stage_id equal to
    the number of stages (e.g. a 3-stage quest completes at new_stage_id=3). This final
    call fires the last stage's on_complete rewards and world effects (XP, items, faction
    reputation) and marks the quest finished — so always issue it when the player wraps up
    the last objective, or those final rewards never apply."""
    return await _update_quest_impl(context, quest_id, new_stage_id)


async def _update_quest_impl(
    context: RunContext[SessionData],
    quest_id: str,
    new_stage_id: int,
    *,
    db_mod=db,
    mutations=db_mutations,
    queries=db_queries,
    content=db_content_queries,
    milestones_mod=milestones,
    activities=db_activity_queries,
    divine_mutations=db_mutations_divine,
) -> str:
    async with db_mod.transaction() as conn:
        pending = await advance_quest_db(
            context,
            quest_id,
            new_stage_id,
            conn=conn,
            mutations=mutations,
            queries=queries,
            content=content,
            milestones_mod=milestones_mod,
            activities=activities,
            divine_mutations=divine_mutations,
        )
    response = finish_quest(context.userdata, pending)
    for event_type, payload in pending.events:
        await publish_game_event(context.userdata.room, event_type, payload, event_bus=context.userdata.event_bus)
    for pid in sorted({pid for pid, _ in pending.item_recipients}):
        await publish_inventory(context.userdata, pid, queries=queries)
    if transition := response.get("scene_transition"):
        from gameplay_agent import set_agent_region

        set_agent_region(context.session.current_agent, transition["region"])
    return json.dumps(response)
