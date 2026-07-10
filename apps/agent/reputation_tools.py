"""Faction reputation DM tool (story-002, M23).

The DM's narrative lever on the player's standing with a whole faction:
adjust_faction_reputation maps a named world event to a fixed delta (reputation.reputation_shift)
and applies it (db_mutations_reputation.adjust_player_faction_reputation) — the faction-scoped
analogue of session_tools.update_npc_disposition (per-NPC). The LLM decides *which* event fired
and narrates the result from the returned standing; the rules own *how much* and the write.

Unlike the disposition tool, this needs no transaction: the writer is a single atomic
additive upsert. Registered on EXPLORATION_TOOLS beside update_npc_disposition (M7's single
region agent exposes world-state mutation verbs everywhere).
"""

import json
import logging

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import db_content_queries
import db_mutations_reputation
from db_errors import db_tool
from reputation import reputation_shift
from session_data import SessionData
from tool_support import _cap_str

logger = logging.getLogger("divineruin.tools")


@function_tool()
@db_tool
async def adjust_faction_reputation(
    context: RunContext[SessionData],
    faction_id: str,
    event_type: str,
    reason: str,
) -> str:
    """Shift the player's reputation with an entire faction after a story event.
    event_type is one of: completed_faction_quest, aided_faction, deescalated_faction,
    attacked_faction, killed_faction_member, betrayed_faction — the magnitude is fixed per
    event. Use when the player's actions change how a whole faction regards them (distinct
    from update_npc_disposition, which shifts a single NPC's feeling)."""
    return await _adjust_faction_reputation_impl(context, faction_id, event_type, reason)


async def _adjust_faction_reputation_impl(
    context: RunContext[SessionData],
    faction_id: str,
    event_type: str,
    reason: str,
    *,
    mutations=db_mutations_reputation,
    content=db_content_queries,
) -> str:
    logger.info("adjust_faction_reputation: faction=%s event=%s reason=%s", faction_id, event_type, reason)
    _cap_str(reason, 256, "reason")
    session: SessionData = context.userdata

    faction = await content.get_faction(faction_id)
    if faction is None:
        raise ToolError(f"Faction '{faction_id}' not found.")

    try:
        delta = reputation_shift(event_type)
    except ValueError as e:
        raise ToolError(str(e)) from e

    new_value = await mutations.adjust_player_faction_reputation(session.player_id, faction_id, delta, reason)

    faction_name = faction.get("name", faction_id)
    session.record_event(f"{faction_name} reputation {delta:+d} -> {new_value} ({event_type}: {reason})")
    response = {
        "faction_id": faction_id,
        "faction_name": faction_name,
        "event_type": event_type,
        "delta": delta,
        "new_value": new_value,
        "reason": reason,
    }
    logger.info("adjust_faction_reputation result: %s %+d -> %s", faction_id, delta, new_value)
    return json.dumps(response)
