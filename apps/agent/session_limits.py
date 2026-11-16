"""Session-owned deadlines; gameplay handoffs and background pauses do not own time."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from session_end import ensure_session_end
from speech_delivery import deliver_speech

if TYPE_CHECKING:
    from livekit.agents import AgentSession

SESSION_CAP_SECONDS = 3600
STEER_SECONDS = 3300
IDLE_CHECK_IN_SECONDS = 300
IDLE_END_SECONDS = 600
logger = logging.getLogger("divineruin.session_limits")


class LimitClock:
    def now(self) -> float:
        return time.monotonic()

    async def wait(self, deadline: float, wake: asyncio.Event) -> None:
        try:
            await asyncio.wait_for(wake.wait(), max(0, deadline - self.now()))
        except TimeoutError:
            pass


class SessionLimits:
    def __init__(self, session: AgentSession, clock: LimitClock, userdata):
        self.session = session
        self.sd = userdata
        self.clock = clock
        self.started = self.last_player = clock.now()
        self.steered = False
        self.suppressed = False
        self.suppression = asyncio.Event()
        self.wake = asyncio.Event()
        self.notifications: dict[str, asyncio.Task] = {}
        self.pending_notifications: set[asyncio.Task] = set()
        self.task: asyncio.Task | None = None
        self.closed = False

    def start(self) -> None:
        self.task = asyncio.create_task(self._run())
        self.task.add_done_callback(self._finished)

    def _finished(self, task: asyncio.Task) -> None:
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.error("Session limits failed", exc_info=error)
            ensure_session_end(self.sd, session=self.session)

    def player_speech(self) -> None:
        if self.closed or self.sd.session_end_task is not None:
            return
        self.last_player = self.clock.now()
        self.suppressed = False
        if self.suppression.is_set():
            self.suppression = asyncio.Event()
        if check_in := self.notifications.get("check-in"):
            check_in.cancel()
        self.wake.set()

    def close(self, _event=None) -> None:
        self.closed = True
        self.session.off("user_input_transcribed", self._solo_speech)
        self.suppression.set()
        self.interrupt_notifications()
        if self.task is not None:
            self.task.cancel()

    async def aclose(self) -> None:
        self.close()
        await asyncio.gather(
            *(task for task in (self.task, *self.pending_notifications) if task is not None),
            return_exceptions=True,
        )

    def _solo_speech(self, event) -> None:
        if self.sd.multiplayer_owner is None and event.transcript.strip():
            self.player_speech()

    def interrupt_notifications(self) -> None:
        for task in self.notifications.values():
            task.cancel()

    def _notify(self, name: str, instruction: str) -> None:
        task = asyncio.create_task(deliver_speech(self.session, instruction, logger, name, tool_choice="none"))
        self.notifications[name] = task
        self.pending_notifications.add(task)
        task.add_done_callback(self._notification_finished)

    def _notification_finished(self, task: asyncio.Task) -> None:
        self.pending_notifications.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.error("Limit notification failed", exc_info=error)

    async def _run(self) -> None:
        while not self.closed and self.sd.session_end_task is None:
            self.wake.clear()
            now = self.clock.now()
            if now >= min(self.started + SESSION_CAP_SECONDS, self.last_player + IDLE_END_SECONDS):
                self.suppressed = True
                self.suppression.set()
                if self.sd.background is not None:
                    self.sd.background.discard_idle_speech()
                self.interrupt_notifications()
                ensure_session_end(
                    self.sd,
                    session=self.session,
                    closing="Speak one brief closing line, bringing this adventure to a resting point.",
                )
                return
            if not self.suppressed and now >= self.last_player + IDLE_CHECK_IN_SECONDS:
                self.suppressed = True
                self.suppression.set()
                if self.sd.background is not None:
                    self.sd.background.discard_idle_speech()
                self._notify("check-in", 'Ask the player once: "Still with me?"')
            if not self.steered and now >= self.started + STEER_SECONDS:
                self.steered = True
                self._notify("steer", "Steer toward a resting point. The session is approaching its end.")
            deadlines = [self.started + SESSION_CAP_SECONDS, self.last_player + IDLE_END_SECONDS]
            if not self.steered:
                deadlines.append(self.started + STEER_SECONDS)
            if not self.suppressed:
                deadlines.append(self.last_player + IDLE_CHECK_IN_SECONDS)
            await self.clock.wait(min(deadlines), self.wake)
