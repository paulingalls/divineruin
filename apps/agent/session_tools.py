"""Session tools — end session, story moments, NPC disposition."""

import asyncio
import json
import logging
from contextvars import copy_context
from functools import partial

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import db
import db_activity_queries
import db_content_queries
import db_mutations
import db_mutations_divine
import db_queries
import event_types as E
from asset_utils import slug_asset_url
from db_errors import db_tool
from game_events import publish_game_event
from role_archetypes import shift_disposition
from session_data import SessionData
from session_end import run_guest_departure
from task_logging import log_task_failure
from tool_preconditions import require_npc_present
from tool_support import MAX_STORY_MOMENTS_PER_PLAYER, STORY_MOMENTS, _cap_str

logger = logging.getLogger("divineruin.tools")


@function_tool()
@db_tool
async def update_npc_disposition(
    context: RunContext[SessionData],
    npc_id: str,
    delta: int,
    reason: str,
) -> str:
    """Shift an NPC's disposition toward or away from the player.
    Delta range: -2 to +2. Positive = warmer, negative = colder.
    Scale: hostile -> unfriendly -> neutral -> friendly -> trusted."""
    return await _update_npc_disposition_impl(context, npc_id, delta, reason)


async def _update_npc_disposition_impl(
    context: RunContext[SessionData],
    npc_id: str,
    delta: int,
    reason: str,
    *,
    db_mod=db,
    mutations=db_mutations,
    queries=db_queries,
    content=db_content_queries,
) -> str:
    logger.info("update_npc_disposition called: npc_id=%s, delta=%d, reason=%s", npc_id, delta, reason)
    _cap_str(reason, 256, "reason")
    session: SessionData = context.userdata
    player_id = session.acting_player_id

    delta = max(-2, min(2, delta))

    npc = await content.get_npc(npc_id)
    if npc is None:
        raise ToolError(f"NPC '{npc_id}' not found.")

    # Stage-driven precondition (story-005): the NPC must be present at the player's
    # current location. M7's collapsed agent exposes this verb in every region, so the
    # guard — not a per-agent tool list — keeps disposition shifts to co-located NPCs.
    await require_npc_present(session.location_id, npc_id, queries=queries)

    pending_events: list[tuple[str, dict]] = []

    async with db_mod.transaction() as conn:
        current = await queries.get_npc_disposition(npc_id, player_id, conn=conn, for_update=True)
        if current is None:
            current = npc.get("default_disposition", "neutral")

        new_disposition = shift_disposition(current, delta, off_ladder="neutral")

        session.validate_acting_player(player_id)
        await mutations.set_npc_disposition(npc_id, player_id, new_disposition, reason, conn=conn)

        pending_events.append(
            (
                E.DISPOSITION_CHANGED,
                {
                    "npc_id": npc_id,
                    "npc_name": npc.get("name", npc_id),
                    "previous": current,
                    "new": new_disposition,
                    "reason": reason,
                },
            )
        )

    for event_type, payload in pending_events:
        await publish_game_event(session.room, event_type, payload, event_bus=session.event_bus)

    npc_name = npc.get("name", npc_id)
    session.record_event(f"{npc_name} disposition: {current} -> {new_disposition} ({reason})")
    session.record_companion_memory(f"Player {reason} with {npc_name}")

    response = {
        "npc_id": npc_id,
        "npc_name": npc_name,
        "previous": current,
        "new": new_disposition,
        "reason": reason,
    }
    logger.info("update_npc_disposition result: %s → %s for %s", current, new_disposition, npc_id)
    return json.dumps(response)


@function_tool()
async def end_session(context: RunContext[SessionData], reason: str) -> str:
    """End the session narratively. Call when the player says they need to go,
    want to wrap up, should stop, or similar goodbye phrases."""
    logger.info("end_session called: reason=%s", reason)
    sd: SessionData = context.userdata
    actor_id = sd.actor_player_id if len(sd.party.members) > 1 else sd.acting_player_id
    member_leaves = len(sd.party.members) > 1
    if member_leaves:
        if sd.departing_player_id is not None:
            raise ToolError("A player departure is already pending")
        sd.departing_player_id = actor_id

    session = context.session

    def after_playout(handle):
        if handle.interrupted or handle.exception() is not None:
            disconnected = sd.reconnection_owner is not None and sd.reconnection_owner.is_disconnected(actor_id)
            if not disconnected:
                sd.departing_player_id = None
                session.generate_reply(
                    instructions=f"Tell {actor_id} their farewell was interrupted and they can say goodbye again."
                )
                return
        if member_leaves:
            departure_context = copy_context()
            departure_context.run(sd._actor_binding.set, None)
            sd.departure_task = asyncio.create_task(
                run_guest_departure(sd, actor_id, session), context=departure_context
            )
            sd.departure_task.add_done_callback(
                partial(log_task_failure, logger=logger, message="Member departure failed")
            )
        else:
            task = asyncio.create_task(session.aclose())
            task.add_done_callback(partial(log_task_failure, logger=logger, message="Session close failed"))

    context.speech_handle.add_done_callback(after_playout)
    if member_leaves:
        instruction = (
            "Only this speaker is leaving; the rest of the party keeps playing. Give this player "
            "a 1-2 sentence personal farewell; do not wrap up the session for anyone else."
        )
    else:
        instruction = (
            "Deliver a 2-3 sentence narrative wrap-up. Find a natural stopping point. "
            "Mention any XP or progress if meaningful. Plant one hook for next session."
        )
    # Always the speaker's own tallies: after a host hand-off the session-wide ones still hold
    # the departed host's earnings, including any from before the last member joined.
    personal = sd.player_summary_metrics.get(actor_id, {})
    stats = {
        "xp_earned": personal.get("xp_earned", 0),
        "items_found": personal.get("items_found", []),
        "quests_progressed": personal.get("quest_progress", []),
        "locations_visited": personal.get("locations_visited", []),
    }
    return json.dumps(
        {
            "status": "ending",
            "session_stats": stats,
            "instruction": instruction,
        }
    )


@function_tool()
@db_tool
async def record_story_moment(
    context: RunContext[SessionData],
    moment_key: str,
    description: str,
) -> str:
    """Record a significant narrative moment during play. Use sparingly —
    only for first combat victory, Hollow discovery, or god contact.
    moment_key must be one of: combat, hollow_encounter, god_contact.
    description is a brief (1-2 sentence) scene summary."""
    return await _record_story_moment_impl(context, moment_key, description)


async def _record_story_moment_impl(
    context: RunContext[SessionData],
    moment_key: str,
    description: str,
    *,
    mutations=db_mutations_divine,
    activities=db_activity_queries,
) -> str:
    logger.info("record_story_moment called: moment_key=%s", moment_key)
    if moment_key not in STORY_MOMENTS:
        raise ToolError(f"Invalid moment_key: '{moment_key}'. Must be one of: {', '.join(sorted(STORY_MOMENTS))}")
    _cap_str(description, 512, "description")

    sd: SessionData = context.userdata
    player_id = sd.acting_player_id
    template_id, asset_id = STORY_MOMENTS[moment_key]
    image_url = slug_asset_url(asset_id)

    count = await activities.count_session_story_moments(sd.session_id, player_id)
    if count >= MAX_STORY_MOMENTS_PER_PLAYER:
        raise ToolError(f"Maximum {MAX_STORY_MOMENTS_PER_PLAYER} story moments per player in this session.")

    sd.validate_acting_player(player_id)
    await mutations.save_story_moment(
        session_id=sd.session_id,
        player_id=player_id,
        moment_key=moment_key,
        description=description,
        template_id=template_id,
        asset_id=asset_id,
    )

    logger.info("record_story_moment saved: %s for session %s", moment_key, sd.session_id)
    return json.dumps(
        {
            "recorded": True,
            "moment_key": moment_key,
            "image_url": image_url,
        }
    )
