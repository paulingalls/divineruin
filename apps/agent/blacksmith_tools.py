"""Intent handoff to/from BlacksmithAgent.

`enter_blacksmith` lets a settlement (City) region agent hand off to BlacksmithAgent
when the player wants to repair gear at a forge; `conclude_blacksmith` hands control
back to the region agent that called it. Mirrors the dispatch enter/conclude
return-to-caller pattern (pre_blacksmith_agent_type stored on SessionData), so control
returns to whichever region agent the player was in.
"""

import json
import logging

from livekit.agents.llm import ChatContext, function_tool
from livekit.agents.voice import RunContext

import db_content_queries
from session_data import SessionData

logger = logging.getLogger("divineruin.tools")


@function_tool()
async def enter_blacksmith(context: RunContext[SessionData]) -> str | tuple:
    """Hand off to the forge to repair damaged gear with the settlement blacksmith.
    Call when the player wants to get an item repaired (or ask a smith what it would
    cost) at a town's forge. Control returns here when they finish."""
    return await _enter_blacksmith_impl(context)


async def _enter_blacksmith_impl(context: RunContext[SessionData]) -> str | tuple:
    from blacksmith_agent import create_blacksmith_agent

    session: SessionData = context.userdata
    # Store the caller's region so conclude_blacksmith returns there. If the caller
    # has no _agent_type (a non-region agent), derive the region from the current
    # location rather than defaulting to City.
    agent_type = getattr(context.session.current_agent, "_agent_type", None)
    if not agent_type:
        agent_type = await db_content_queries.get_location_region_type(session.location_id)
    session.pre_blacksmith_agent_type = agent_type
    logger.info("enter_blacksmith: from %s", session.pre_blacksmith_agent_type)

    parts = ["The player steps up to the settlement forge to see the blacksmith about their gear."]
    if session.companion and session.companion.is_present:
        parts.append(f"{session.companion.name} is with them.")
    parts.append("Open the scene with the heat and ring of the forge; ask what they need mended.")
    blacksmith_ctx = ChatContext()
    blacksmith_ctx.add_message(role="system", content=" ".join(parts))

    return create_blacksmith_agent(chat_ctx=blacksmith_ctx), json.dumps({"status": "entered_blacksmith"})


@function_tool()
async def conclude_blacksmith(context: RunContext[SessionData]) -> str | tuple:
    """Return from the forge to ordinary play. Call when the player is done with
    repairs and wants to get back to the adventure."""
    return await _conclude_blacksmith_impl(context)


async def _conclude_blacksmith_impl(context: RunContext[SessionData]) -> str | tuple:
    from gameplay_agent import create_gameplay_agent

    session: SessionData = context.userdata
    agent_type = session.pre_blacksmith_agent_type
    if not agent_type:
        # Reached without a stored caller: derive the region from the current
        # location rather than defaulting to City.
        agent_type = await db_content_queries.get_location_region_type(session.location_id)
    session.pre_blacksmith_agent_type = None
    logger.info("conclude_blacksmith: back to %s", agent_type)

    parts = ["The player steps away from the forge, gear seen to, ready to continue."]
    if session.companion and session.companion.is_present:
        parts.append(f"{session.companion.name} is at their side.")
    summary_ctx = ChatContext()
    summary_ctx.add_message(role="system", content=" ".join(parts))

    return create_gameplay_agent(
        agent_type, session.location_id, companion=session.companion, chat_ctx=summary_ctx
    ), json.dumps({"status": "concluded_blacksmith"})
