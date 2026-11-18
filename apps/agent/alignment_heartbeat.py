"""Session-owned clock for committed patron deed judgments."""

import logging
import time
from collections.abc import Callable

import asyncpg

import db
from game_events import publish_game_event
from patron_deeds import judge_pending_deeds
from session_data import SessionData

logger = logging.getLogger("divineruin.alignment")
TRANSIENT_IO_ERRORS = (OSError, TimeoutError, asyncpg.PostgresError, asyncpg.InterfaceError)


class AlignmentHeartbeat:
    def __init__(
        self, session_data: SessionData, *, interval_s: float = 1200, now: Callable[[], float] = time.monotonic
    ) -> None:
        self._sd = session_data
        self._interval_s = interval_s
        self._now = now
        self._last_tick = now()

    async def maybe_tick(self) -> None:
        now = self._now()
        if now - self._last_tick < self._interval_s:
            return
        member_ids = self._sd.present_member_ids
        events = []
        grants = []
        try:
            async with db.transaction() as conn:
                for player_id in member_ids:
                    grant = await judge_pending_deeds(player_id, conn=conn, pending_events=events)
                    if grant is not None and grant.new_level != grant.previous_level:
                        grants.append((player_id, grant))
        except TRANSIENT_IO_ERRORS:
            logger.exception("Patron deed judgment failed; retrying next iteration")
            return

        # A transport failure cannot undo the committed judgment or restart its clock.
        self._last_tick = now
        for player_id, grant in grants:
            delta = grant.new_level - grant.previous_level
            self._sd.record_event(
                f"Patron deed judgment: {player_id}, patron {grant.patron_id}, favor {delta:+d} to {grant.new_level}."
            )
        for event_type, payload in events:
            await publish_game_event(self._sd.room, event_type, payload, event_bus=self._sd.event_bus)
