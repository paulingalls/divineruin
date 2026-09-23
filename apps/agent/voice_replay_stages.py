"""Per-stage timings for one voice-replay row, so a slow turn names the slow stage.

Each `at_ms`/`done_at_ms` is when the runner observed the event, measured on the
same monotonic clock as the source clip's speech end. Delays and TTFT/TTFB values
are LiveKit's own measurements for that stage.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from livekit.agents.metrics import LLMMetrics, TTSMetrics

_USER_KEYS = ("transcription_delay", "end_of_turn_delay", "on_user_turn_completed_delay")
_ASSISTANT_KEYS = ("llm_node_ttft", "llm_node_ttfs", "tts_node_ttfb", "e2e_latency")
GAME_EVENTS_TOPIC = "game_events"


def _ms(seconds: float) -> float:
    return round(seconds * 1000, 1)


class StageRecorder:
    def __init__(self, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self._user: list[tuple[float, dict[str, Any]]] = []
        self._assistant: list[tuple[float, dict[str, Any]]] = []
        self._llm: list[tuple[float, LLMMetrics]] = []
        self._tts: list[tuple[float, TTSMetrics]] = []
        self._tools: list[float] = []
        self._events: list[tuple[float, str]] = []

    def on_conversation_item(self, event: Any) -> None:
        item = event.item
        role = getattr(item, "role", None)
        metrics = getattr(item, "metrics", None) or {}
        if role == "user" and metrics:
            self._user.append((self._now(), dict(metrics)))
        elif role == "assistant" and metrics:
            self._assistant.append((self._now(), dict(metrics)))

    def on_llm_metrics(self, metrics: LLMMetrics) -> None:
        self._llm.append((self._now(), metrics))

    def on_tts_metrics(self, metrics: TTSMetrics) -> None:
        self._tts.append((self._now(), metrics))

    def on_tools_executed(self, _event: Any) -> None:
        self._tools.append(self._now())

    def on_data_received(self, packet: Any) -> None:
        """Player-side arrival of a game event: the client plays SFX (dice, chimes) from these."""
        if packet.topic != GAME_EVENTS_TOPIC:
            return
        observed = self._now()
        try:
            event_type = str(json.loads(packet.data)["type"])
        except (ValueError, KeyError, TypeError):
            event_type = "<unparseable>"
        self._events.append((observed, event_type))

    def report(self, *, speech_end_monotonic: float) -> dict[str, Any]:
        def at(observed: float) -> float:
            return _ms(observed - speech_end_monotonic)

        def picked(metrics: dict[str, Any], keys: tuple[str, ...]) -> dict[str, float]:
            return {f"{key}_ms": _ms(metrics[key]) for key in keys if metrics.get(key) is not None}

        return {
            "user": [{"at_ms": at(t), **picked(m, _USER_KEYS)} for t, m in self._user],
            "llm_requests": [
                {
                    "done_at_ms": at(t),
                    "ttft_ms": _ms(m.ttft),
                    "duration_ms": _ms(m.duration),
                    "prompt_tokens": m.prompt_tokens,
                    "cached_tokens": m.prompt_cached_tokens,
                    "completion_tokens": m.completion_tokens,
                }
                for t, m in self._llm
            ],
            "tools_executed_at_ms": [at(t) for t in self._tools],
            "tts_requests": [
                {"done_at_ms": at(t), "ttfb_ms": _ms(m.ttfb), "characters": m.characters_count} for t, m in self._tts
            ],
            "assistant": [{"at_ms": at(t), **picked(m, _ASSISTANT_KEYS)} for t, m in self._assistant],
            "game_events": [{"at_ms": at(t), "type": event_type} for t, event_type in self._events],
        }
