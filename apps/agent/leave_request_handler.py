"""Session-scoped explicit Leave over LiveKit's authenticated data channel."""

import asyncio
import json
import logging
from functools import partial

from livekit import rtc
from livekit.agents import AgentSession

import event_types as E
import room_admin
import session_outcome
from card_tap_handler import PLAYER_HINTS_TOPIC, authorized_hint_actor
from session_data import SessionData
from session_end import ensure_session_end, run_guest_departure
from task_logging import log_task_failure

logger = logging.getLogger("divineruin.leave_request")


class LeaveRequestHandler:
    def __init__(self, room: rtc.Room, session: AgentSession, userdata: SessionData) -> None:
        self.room, self.session, self.sd = room, session, userdata
        self.close_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self.room.on("data_received", self._received)

    def stop(self, _event: object = None) -> None:
        self.room.off("data_received", self._received)

    def _received(self, packet: rtc.DataPacket) -> None:
        if packet.topic != PLAYER_HINTS_TOPIC:
            return
        try:
            payload = json.loads(packet.data)
        except (ValueError, TypeError):
            return
        if not isinstance(payload, dict) or payload.get("type") != E.LEAVE_REQUESTED:
            return
        sender = packet.participant.identity if packet.participant else ""
        if authorized_hint_actor(self.sd, sender) is None:
            return
        if self.sd.session_end_task is not None or self.sd.departing_player_id is not None:
            return
        if self.sd.background is None:
            # Creation and onboarding have no recap to publish; end the room for the player now
            # rather than leave their client "wrapping up" until its fallback.
            if self.close_task is not None:
                return
            self.close_task = asyncio.create_task(self._end_before_gameplay(sender))
            self.sd.session_end_task = self.close_task
            task = self.close_task
        elif len(self.sd.party.members) > 1:
            self.sd.departing_player_id = sender
            self.sd.departure_task = asyncio.create_task(run_guest_departure(self.sd, sender, self.session))
            task = self.sd.departure_task
        else:
            end = ensure_session_end(self.sd)
            self.close_task = asyncio.create_task(self._close_after(end))
            task = self.close_task
        task.add_done_callback(partial(log_task_failure, logger=logger, message="Leave failed"))

    async def _end_before_gameplay(self, sender: str) -> None:
        try:
            await room_admin.remove_player(self.room.name, sender)
        finally:
            try:
                await session_outcome.complete(self.sd.primary_player_id, self.sd.session_id, "failed")
            finally:
                await self.session.aclose()

    async def _close_after(self, end: asyncio.Task[None]) -> None:
        try:
            await asyncio.shield(end)
        finally:
            await self.session.aclose()
