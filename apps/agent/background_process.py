"""Background process: event loop, warm layer rebuild, proactive speech, guidance."""

from __future__ import annotations

import asyncio
import enum
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from event_bus import GameEvent
from prompts import build_warm_layer, build_full_prompt, SYSTEM_PROMPT

if TYPE_CHECKING:
    from livekit.agents import Agent, AgentSession
    from session_data import SessionData

logger = logging.getLogger("divineruin.background")

REBUILD_EVENT_TYPES = {"location_changed", "quest_updated", "disposition_changed"}

GUIDANCE_LEVEL_2_SECS = 35.0

TIMER_FALLBACK_SECS = 30.0


class SpeechPriority(enum.IntEnum):
    ROUTINE = 0
    IMPORTANT = 1
    CRITICAL = 2


@dataclass(order=True)
class PendingSpeech:
    priority: SpeechPriority
    instructions: str = field(compare=False)
    created: float = field(default_factory=time.time, compare=False)


class BackgroundProcess:
    def __init__(
        self,
        agent: Agent,
        session: AgentSession,
        session_data: SessionData,
    ) -> None:
        self._agent = agent
        self._session = session
        self._sd = session_data
        self._task: asyncio.Task | None = None
        self._last_warm_layer: str = ""
        self._speech_queue: list[PendingSpeech] = []
        self._stop = False
        self._last_guidance_time: float = 0.0

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        # Initial warm layer build
        await self._rebuild_warm_layer()
        logger.info("Background process started")

        while not self._stop:
            event = await self._sd.event_bus.get(timeout=TIMER_FALLBACK_SECS)

            events: list[GameEvent] = []
            if event is not None:
                events.append(event)
            events.extend(self._sd.event_bus.drain())

            needs_rebuild = self._handle_events(events)

            if needs_rebuild or event is None:
                await self._rebuild_warm_layer()

            self._check_guidance()

            await self._deliver_speech()

    def _handle_events(self, events: list[GameEvent]) -> bool:
        needs_rebuild = False
        for ev in events:
            if ev.event_type in REBUILD_EVENT_TYPES:
                needs_rebuild = True

            if ev.event_type == "location_changed":
                new_loc = ev.payload.get("new_location", "")
                self._queue_speech(
                    SpeechPriority.IMPORTANT,
                    f"The player just arrived at a new location ({new_loc}). "
                    "If a companion is present, have them make a brief observation "
                    "about the new surroundings — one sentence, in character.",
                )

            elif ev.event_type == "quest_updated":
                quest_name = ev.payload.get("quest_name", "unknown quest")
                objective = ev.payload.get("objective", "")
                self._queue_speech(
                    SpeechPriority.IMPORTANT,
                    f"The quest '{quest_name}' just progressed. New objective: {objective}. "
                    "If a companion is present, have them comment briefly on the "
                    "quest progression — one sentence, in character.",
                )

        return needs_rebuild

    def _check_guidance(self) -> None:
        if self._sd.in_combat:
            return

        if self._sd.last_player_speech_time <= 0:
            return

        # Don't nudge again if player hasn't spoken since last nudge
        if self._last_guidance_time >= self._sd.last_player_speech_time:
            return

        silence = time.time() - self._sd.last_player_speech_time

        if silence >= GUIDANCE_LEVEL_2_SECS:
            self._last_guidance_time = time.time()
            hints = self._get_quest_hints()
            hint_text = f" Consider using this hint: {hints[0]}" if hints else ""
            self._queue_speech(
                SpeechPriority.IMPORTANT,
                "The player has been quiet for a while. Have a companion "
                "offer a gentle suggestion about what to do next — "
                f"one sentence, in character.{hint_text}",
            )

    def _get_quest_hints(self) -> list[str]:
        # Pull hints from recent events or session data if available
        # This is a lightweight check — the warm layer has full quest data
        return []

    def _queue_speech(self, priority: SpeechPriority, instructions: str) -> None:
        self._speech_queue.append(PendingSpeech(priority=priority, instructions=instructions))

    async def _deliver_speech(self) -> None:
        if not self._speech_queue:
            return

        top = max(self._speech_queue)
        self._speech_queue.clear()

        try:
            await self._session.generate_reply(instructions=top.instructions)
            logger.info("Proactive speech delivered (priority=%s)", top.priority.name)
        except Exception:
            logger.warning("Failed to deliver proactive speech", exc_info=True)

    async def _rebuild_warm_layer(self) -> None:
        try:
            warm = await build_warm_layer(
                self._sd.location_id,
                self._sd.player_id,
                self._sd.world_time,
            )
        except Exception:
            logger.warning("Warm layer build failed", exc_info=True)
            return

        if warm == self._last_warm_layer:
            return

        self._last_warm_layer = warm
        full_prompt = build_full_prompt(SYSTEM_PROMPT, warm)
        self._agent.instructions = full_prompt
        logger.info("Warm layer updated (%d chars)", len(warm))
