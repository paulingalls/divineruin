import json

from livekit.agents import Agent
from livekit.agents.llm import ChatContext, function_tool
from livekit.agents.voice import RunContext

import db_content_queries
import db_queries
from db_errors import db_tool
from session_data import SessionData


async def _enter_trade_impl(context: RunContext[SessionData]) -> tuple[Agent, str]:
    from merchant_agent import MerchantAgent

    session = context.userdata
    caller = context.session.current_agent
    region = getattr(caller, "_agent_type", None) or await db_content_queries.get_location_region_type(
        session.location_id
    )
    present = await db_queries.get_npcs_at_location(session.location_id)
    npcs = [{"id": npc["id"], "name": npc["name"], "voice_id": npc.get("voice_id")} for npc in present]
    chat = ChatContext()
    chat.add_message(
        role="system",
        content=f"Present NPCs at {session.location_id} (id, name and voice key):\n{json.dumps(npcs)}",
    )

    for message in reversed(caller.chat_ctx.messages()):
        if message.role == "user" and message.text_content:
            chat.add_message(role="user", content=message.text_content)
            break

    merchant = MerchantAgent(chat_ctx=chat)
    session.pre_trade_agent_type = region
    return merchant, json.dumps({"status": "entered_trade", "location_id": session.location_id, "present_npcs": npcs})


@function_tool()
@db_tool
async def conclude_trade(context: RunContext[SessionData]) -> tuple[Agent, str]:
    """Return to ordinary play when the player is finished selling or wants to leave."""
    from gameplay_agent import create_gameplay_agent

    session = context.userdata
    region = session.pre_trade_agent_type or await db_content_queries.get_location_region_type(session.location_id)
    chat = ChatContext()
    chat.add_message(role="system", content="The trade conversation is finished. Continue at the current location.")
    exploration = create_gameplay_agent(region, session.location_id, companion=session.companion, chat_ctx=chat)
    session.pre_trade_agent_type = None
    return exploration, json.dumps({"status": "concluded_trade"})
