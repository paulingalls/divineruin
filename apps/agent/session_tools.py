"""Session tools — end session, story moments, NPC disposition."""

import json
import logging

from livekit.agents.llm import function_tool
from livekit.agents.voice import RunContext

import db
import db_activity_queries
import db_content_queries
import db_mutations
import db_queries
import event_types as E
from asset_utils import slug_asset_url
from db_errors import db_tool
from game_events import publish_game_event
from quest_tools import _clamp_disposition_shift
from session_data import SessionData
from tools import MAX_STORY_MOMENTS_PER_SESSION, STORY_MOMENTS, _cap_str

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
    Scale: hostile -> wary -> neutral -> friendly -> trusted."""
    logger.info("update_npc_disposition called: npc_id=%s, delta=%d, reason=%s", npc_id, delta, reason)
    cap_err = _cap_str(reason, 256, "reason")
    if cap_err:
        return cap_err
    session: SessionData = context.userdata

    delta = max(-2, min(2, delta))

    # Cached content read — outside transaction
    npc = await db_content_queries.get_npc(npc_id)
    if npc is None:
        return json.dumps({"error": f"NPC '{npc_id}' not found."})

    pending_events: list[tuple[str, dict]] = []

    async with db.transaction() as conn:
        current = await db_queries.get_npc_disposition(npc_id, session.player_id, conn=conn, for_update=True)
        if current is None:
            current = npc.get("default_disposition", "neutral")

        new_disposition = _clamp_disposition_shift(current, delta)

        await db_mutations.set_npc_disposition(npc_id, session.player_id, new_disposition, reason, conn=conn)

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
    sd.ending_requested = True
    return json.dumps(
        {
            "status": "ending",
            "session_stats": {
                "xp_earned": sd.session_xp_earned,
                "items_found": sd.session_items_found,
                "quests_progressed": sd.session_quests_progressed,
                "locations_visited": sd.session_locations_visited,
            },
            "instruction": "Deliver a 2-3 sentence narrative wrap-up. Find a natural stopping point. "
            "Mention any XP or progress if meaningful. Plant one hook for next session.",
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
    logger.info("record_story_moment called: moment_key=%s", moment_key)
    if moment_key not in STORY_MOMENTS:
        return json.dumps(
            {"error": f"Invalid moment_key: '{moment_key}'. Must be one of: {', '.join(sorted(STORY_MOMENTS))}"}
        )
    cap_err = _cap_str(description, 512, "description")
    if cap_err:
        return cap_err

    sd: SessionData = context.userdata
    template_id, asset_id = STORY_MOMENTS[moment_key]
    image_url = slug_asset_url(asset_id)

    # Enforce per-session limit
    count = await db_activity_queries.count_session_story_moments(sd.session_id)
    if count >= MAX_STORY_MOMENTS_PER_SESSION:
        return json.dumps({"error": f"Maximum {MAX_STORY_MOMENTS_PER_SESSION} story moments per session."})

    await db_mutations.save_story_moment(
        session_id=sd.session_id,
        player_id=sd.player_id,
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
