"""Record an authored action for the acting player's patron."""

import json

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import db
import db_activity_queries
import db_queries
from _gods_content import load_gods
from game_events import publish_game_event
from patron_favor import get_patron_tier
from progression_tools import _award_divine_favor_core
from session_data import SessionData


@function_tool()
async def record_patron_action(context: RunContext[SessionData], action_id: str) -> str:
    """Record a completed player action that clearly matches an authored patron action id.

    Use an id previously seen in query_info(kind="patron") for this player's patron.
    Call only after the player actually takes the action, never for an intention.
    """
    return await _record_patron_action_impl(context, action_id)


async def _record_patron_action_impl(context: RunContext[SessionData], action_id: str) -> str:
    if not action_id or not action_id.strip():
        raise ToolError("action_id is required")

    session = context.userdata
    player_id = session.acting_player_id
    session.validate_acting_player(player_id)
    pending_events: list[tuple[str, dict]] = []

    async with db.transaction() as conn:
        if await db_queries.get_player(player_id, conn=conn, for_update=True) is None:
            raise ToolError(f"Player '{player_id}' not found")
        favor = await db_activity_queries.get_divine_favor(player_id, conn=conn)
        if favor is None or favor.get("patron", "none") == "none":
            raise ToolError("Player is Unbound")

        patron = next((god for god in load_gods() if god["god_id"] == favor["patron"]), None)
        if patron is None:
            raise ToolError(f"Unknown patron '{favor['patron']}'")
        rows = patron["favor_actions"]["positive"] + patron["favor_actions"]["negative"]
        action = next((row for row in rows if row["action"] == action_id), None)
        if action is None:
            raise ToolError(f"Action '{action_id}' is not authored for {favor['patron']}")

        try:
            grant = await _award_divine_favor_core(
                player_id,
                action["amount"],
                f"Patron action '{action_id}'",
                conn=conn,
                pending_events=pending_events,
            )
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        if grant is None:
            raise ToolError("Player has no patron favor")

        result = {
            "action_id": action_id,
            "amount_applied": grant.new_level - grant.previous_level,
            "level": grant.new_level,
            "max": favor["max"],
            "tier": get_patron_tier({**favor, "level": grant.new_level}),
            "previous_tier": get_patron_tier(favor),
        }

    for event_type, payload in pending_events:
        await publish_game_event(session.room, event_type, payload, event_bus=session.event_bus)
    return json.dumps(result)
