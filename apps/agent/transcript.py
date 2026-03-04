"""Transcript logger — writes session conversation to file and publishes to data channel."""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING

from dialogue_parser import DEFAULT_CHARACTER
from game_events import publish_game_event

if TYPE_CHECKING:
    from livekit import rtc

    from event_bus import EventBus

DEFAULT_LOG_PATH = os.path.join(os.path.dirname(__file__), "transcript.log")

_instance_counter = 0


def _ts() -> str:
    return time.strftime("%H:%M:%S")


class TranscriptLogger:
    """Logs conversation turns to a file and publishes transcript_entry events."""

    def __init__(
        self,
        room: rtc.Room | None,
        event_bus: EventBus | None = None,
        log_path: str = DEFAULT_LOG_PATH,
    ) -> None:
        global _instance_counter
        self._room = room
        self._event_bus = event_bus

        _instance_counter += 1
        self._logger = logging.getLogger(f"divineruin.transcript.{_instance_counter}")
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False

        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        self._logger.addHandler(handler)

    def close(self) -> None:
        """Close file handlers to prevent descriptor leaks across sessions."""
        for handler in self._logger.handlers[:]:
            handler.close()
            self._logger.removeHandler(handler)

    def _write(self, line: str) -> None:
        self._logger.info(line)

    async def _publish(
        self,
        speaker: str,
        text: str,
        character: str | None = None,
        emotion: str | None = None,
    ) -> None:
        await publish_game_event(
            self._room,
            "transcript_entry",
            {
                "speaker": speaker,
                "character": character,
                "emotion": emotion,
                "text": text,
                "timestamp": time.time(),
            },
            self._event_bus,
        )

    async def log_player(self, text: str) -> None:
        """Log player speech from STT."""
        self._write(f"[{_ts()}] PLAYER: {text}")
        await self._publish("player", text)

    async def log_dm(self, character: str, emotion: str, text: str) -> None:
        """Log DM/NPC speech from TTS segments."""
        if character == DEFAULT_CHARACTER:
            self._write(f"[{_ts()}] DM: {text}")
            await self._publish("dm", text)
        else:
            self._write(f"[{_ts()}] [{character}, {emotion}]: {text}")
            await self._publish("npc", text, character=character, emotion=emotion)

    async def log_tool(self, tool_name: str, args_summary: str, result_summary: str) -> None:
        """Log tool invocations."""
        self._write(f"[{_ts()}] TOOL({tool_name}): {args_summary} -> {result_summary}")
        await self._publish("tool", f"{tool_name}: {result_summary}")
