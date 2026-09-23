"""Session end: the recap the player hears, fired once — when the SESSION closes.

Not on an agent's ``on_exit``. That runs on every mode handoff (``AgentActivity.drain``
awaits it, agent_activity.py:919-932), so a SESSION_END published there reached the client
on the way into every fight and flipped it to the end-of-session summary screen
(``apps/mobile/src/audio/game-event-handler.ts:264-291``). Debt 2009d9ef.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import db_mutations
import event_types as E
import room_admin
from game_events import publish_game_event
from host_handoff import promote_after_departure
from session_summary import generate_session_summary

if TYPE_CHECKING:
    from session_data import SessionData

logger = logging.getLogger("divineruin.session_end")


async def run_guest_departure(sd: SessionData, player_id: str, session) -> None:
    """Complete one member's goodbye after their turn has finished playing."""
    end_published = False
    removed = False
    saved = False
    try:
        if sd.departing_player_id != player_id or not sd.party.contains(player_id):
            raise RuntimeError(f"No pending departure for {player_id!r}")
        if sd.room is None or not sd.room.name:
            raise RuntimeError("Guest departure requires a named LiveKit room")
        lifecycle = sd.multiplayer_owner.lifecycle if sd.multiplayer_owner else None
        if lifecycle is None:
            raise RuntimeError("Guest departure requires party lifecycle")
        payload = await generate_session_summary(sd, sd.transcript_path, sd.session_start_time, player_id=player_id)
        payload = {**payload, "player_id": player_id}
        await publish_game_event(sd.room, E.SESSION_END, payload, sd.event_bus)
        end_published = True
        await room_admin.remove_player(sd.room.name, player_id)
        removed = True
        lifecycle.mark_departed(player_id)
        if player_id == sd.primary_player_id:
            await db_mutations.save_session_summary(player_id, sd.session_id, payload)
            saved = True
            await promote_after_departure(sd, player_id, session)
        else:
            sd.party.members[:] = [member for member in sd.party.members if member.player_id != player_id]
            await db_mutations.save_session_summary(player_id, sd.session_id, payload)
            saved = True
    except Exception:
        logger.exception("Guest departure failed for %s", player_id)
        if end_published and not removed:
            try:
                await publish_game_event(
                    sd.room, E.SESSION_END, {"player_id": player_id, "cancelled": True}, sd.event_bus
                )
            except Exception:
                logger.exception("Failed to cancel guest end event for %s", player_id)
        if saved:
            instruction = "Tell the party the departure completed but the new primary could not be prepared."
        elif removed:
            instruction = "Tell the party briefly that the member left but their recap could not be saved."
        else:
            instruction = "Tell the party briefly that the departure failed and they can try again."
        session.generate_reply(instructions=instruction)
        raise
    finally:
        sd.departing_player_id = None


async def run_session_end(sd: SessionData) -> None:
    """Generate the session summary, publish it to the client, and store the row.

    Every input is session-scoped, read off ``SessionData``: an agent instance knows only
    its own slice of the session, and the recap covers the whole of it.
    """
    payload = await generate_session_summary(sd, sd.transcript_path, sd.session_start_time)

    results = await asyncio.gather(
        publish_game_event(sd.room, E.SESSION_END, payload, sd.event_bus),
        db_mutations.save_session_summary(sd.primary_player_id, sd.session_id, payload),
        return_exceptions=True,
    )
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            labels = ("publish session_end", "save session summary")
            logger.exception("Failed to %s", labels[i], exc_info=result)
