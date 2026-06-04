"""Intent handoff to/from DispatchAgent.

`_enter_dispatch_impl` (the dispatch-entry handoff behind enter_mode(mode="dispatch"),
mode_tools.py) lets any region agent hand off to DispatchAgent when the player wants a
deliberate between-adventure activity (training; companion errands in story-009)
without travelling; `conclude_dispatch` hands control back to the agent that called it.
Mirrors the combat return-to-caller pattern (pre_dispatch_agent_type stored on
SessionData), so control returns to whichever region agent the player was in.
"""

import json
import logging

from livekit.agents.llm import ChatContext, function_tool
from livekit.agents.voice import RunContext

import db_content_queries
from session_data import SessionData

logger = logging.getLogger("divineruin.tools")


async def _enter_dispatch_impl(context: RunContext[SessionData]) -> str | tuple:
    from dispatch_agent import create_dispatch_agent

    session: SessionData = context.userdata
    # Store the caller's region so conclude_dispatch returns there. If the caller
    # has no _agent_type (a non-region agent), derive the region from the current
    # location rather than defaulting to City — so a non-city hall routes back right.
    agent_type = getattr(context.session.current_agent, "_agent_type", None)
    if not agent_type:
        agent_type = await db_content_queries.get_location_region_type(session.location_id)
    session.pre_dispatch_agent_type = agent_type
    logger.info("enter_dispatch: from %s", session.pre_dispatch_agent_type)

    parts = ["The player turns to a deliberate between-adventure activity (training, or managing companions)."]
    if session.companion and session.companion.is_present:
        parts.append(f"{session.companion.name} is with them.")
    parts.append("Open the scene calmly; ask what they want to do.")
    dispatch_ctx = ChatContext()
    dispatch_ctx.add_message(role="system", content=" ".join(parts))

    return create_dispatch_agent(chat_ctx=dispatch_ctx), json.dumps({"status": "entered_dispatch"})


@function_tool()
async def conclude_dispatch(context: RunContext[SessionData]) -> str | tuple:
    """Return from the dispatch context to ordinary play. Call when the player is
    done training or managing companions and wants to get back to the adventure."""
    return await _conclude_dispatch_impl(context)


async def _conclude_dispatch_impl(context: RunContext[SessionData]) -> str | tuple:
    from gameplay_agent import create_gameplay_agent

    session: SessionData = context.userdata
    agent_type = session.pre_dispatch_agent_type
    if not agent_type:
        # Reached via the location route (no stored caller): derive the region from
        # the current location rather than defaulting to City.
        agent_type = await db_content_queries.get_location_region_type(session.location_id)
    session.pre_dispatch_agent_type = None
    logger.info("conclude_dispatch: back to %s", agent_type)

    parts = ["The player steps back out into the world, ready to continue."]
    if session.companion and session.companion.is_present:
        parts.append(f"{session.companion.name} is at their side.")
    summary_ctx = ChatContext()
    summary_ctx.add_message(role="system", content=" ".join(parts))

    return create_gameplay_agent(
        agent_type, session.location_id, companion=session.companion, chat_ctx=summary_ctx
    ), json.dumps({"status": "concluded_dispatch"})
