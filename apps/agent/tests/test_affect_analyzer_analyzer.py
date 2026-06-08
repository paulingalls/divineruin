"""Tests for the stateful PlayerAffectAnalyzer + format_affect_context (Phase A).

The analyzer object (latency tracking, affect-vector assembly, async run loop)
and its warm-prompt formatting — split from the pure-function tests
(test_affect_analyzer_functions.py) to keep each file under the 500-line cap.
"""

import asyncio
import time

from livekit.agents.language import LanguageCode
from livekit.agents.stt import SpeechData, SpeechEvent, SpeechEventType
from livekit.agents.types import TimedString

from affect_analyzer import PlayerAffectAnalyzer
from warm_prompts import format_affect_context

# ---------------------------------------------------------------------------
# Response latency edge cases
# ---------------------------------------------------------------------------


class TestResponseLatency:
    def test_no_tts_end_recorded(self):
        analyzer = PlayerAffectAnalyzer()
        # No record_tts_end called → latency should be 0
        event = _make_speech_event("hello there")
        analyzer._process_stt_event(event)
        vec = analyzer.get_current_vector()
        assert vec is not None
        assert vec["response_latency_ms"] == 0

    def test_normal_latency(self):
        analyzer = PlayerAffectAnalyzer()
        analyzer.record_tts_end()
        # Small delay
        time.sleep(0.05)
        event = _make_speech_event("I look around")
        analyzer._process_stt_event(event)
        vec = analyzer.get_current_vector()
        assert vec is not None
        assert vec["response_latency_ms"] >= 40  # At least ~50ms

    def test_interruption_clamped_to_zero(self):
        analyzer = PlayerAffectAnalyzer()
        # Set TTS end in the future (simulates interruption)
        analyzer._last_tts_end = time.monotonic() + 10
        event = _make_speech_event("wait stop")
        analyzer._process_stt_event(event)
        vec = analyzer.get_current_vector()
        assert vec is not None
        assert vec["response_latency_ms"] == 0

    def test_latency_capped_at_30s(self):
        analyzer = PlayerAffectAnalyzer()
        # Set TTS end far in the past
        analyzer._last_tts_end = time.monotonic() - 60
        event = _make_speech_event("hello")
        analyzer._process_stt_event(event)
        vec = analyzer.get_current_vector()
        assert vec is not None
        assert vec["response_latency_ms"] == 30_000


# ---------------------------------------------------------------------------
# Affect vector structure
# ---------------------------------------------------------------------------


class TestAffectVector:
    def test_all_keys_present(self):
        analyzer = PlayerAffectAnalyzer()
        event = _make_speech_event("I want to explore the ruins, what's inside?")
        analyzer._process_stt_event(event)
        vec = analyzer.get_current_vector()
        assert vec is not None

        assert "engagement" in vec
        assert "level" in vec["engagement"]
        assert "trend" in vec["engagement"]
        assert "signals" in vec["engagement"]

        assert "energy" in vec
        assert "speech_rate_wps" in vec["energy"]
        assert "rate_vs_baseline" in vec["energy"]

        assert "interaction_style" in vec
        assert "mode" in vec["interaction_style"]
        assert "signals" in vec["interaction_style"]

        assert "response_latency_ms" in vec
        assert "latency_vs_baseline" in vec
        assert "turn_number" in vec
        assert "session_duration_min" in vec
        assert "calibration_confidence" in vec

    def test_calibration_low_at_turn_1(self):
        analyzer = PlayerAffectAnalyzer()
        event = _make_speech_event("hello")
        analyzer._process_stt_event(event)
        vec = analyzer.get_current_vector()
        assert vec is not None
        assert vec["calibration_confidence"] == "low"

    def test_calibration_medium_at_turn_3(self):
        analyzer = PlayerAffectAnalyzer()
        for text in ["hello", "yes", "I look around the room"]:
            analyzer._process_stt_event(_make_speech_event(text))
        vec = analyzer.get_current_vector()
        assert vec is not None
        assert vec["calibration_confidence"] == "medium"

    def test_calibration_high_at_turn_6(self):
        analyzer = PlayerAffectAnalyzer()
        texts = ["hello", "yes", "what's that", "I go north", "tell me more", "interesting"]
        for text in texts:
            analyzer._process_stt_event(_make_speech_event(text))
        vec = analyzer.get_current_vector()
        assert vec is not None
        assert vec["calibration_confidence"] == "high"

    def test_none_before_any_events(self):
        analyzer = PlayerAffectAnalyzer()
        assert analyzer.get_current_vector() is None


# ---------------------------------------------------------------------------
# Integration: async _process_stt_event with mock SpeechEvent
# ---------------------------------------------------------------------------


class TestProcessSttEvent:
    def test_final_transcript_updates_vector(self):
        analyzer = PlayerAffectAnalyzer()
        event = _make_speech_event("I want to investigate the strange noise")
        analyzer._process_stt_event(event)
        vec = analyzer.get_current_vector()
        assert vec is not None
        assert vec["turn_number"] == 1

    def test_ignores_interim_transcript(self):
        analyzer = PlayerAffectAnalyzer()
        event = _make_speech_event("partial", event_type=SpeechEventType.INTERIM_TRANSCRIPT)
        analyzer._process_stt_event(event)
        assert analyzer.get_current_vector() is None

    def test_ignores_empty_text(self):
        analyzer = PlayerAffectAnalyzer()
        event = _make_speech_event("")
        analyzer._process_stt_event(event)
        assert analyzer.get_current_vector() is None

    def test_ignores_whitespace_only(self):
        analyzer = PlayerAffectAnalyzer()
        event = _make_speech_event("   ")
        analyzer._process_stt_event(event)
        assert analyzer.get_current_vector() is None


class TestAsyncRun:
    async def test_processes_queued_event(self):
        analyzer = PlayerAffectAnalyzer()
        analyzer.start()
        event = _make_speech_event("I open the heavy door")
        analyzer.enqueue_event(event)
        await asyncio.sleep(0.2)
        vec = analyzer.get_current_vector()
        assert vec is not None
        assert vec["turn_number"] == 1
        await analyzer.stop()

    async def test_stop_cleans_up_task(self):
        analyzer = PlayerAffectAnalyzer()
        analyzer.start()
        assert analyzer._task is not None
        assert not analyzer._task.done()
        await analyzer.stop()
        assert analyzer._task is None

    async def test_start_recovers_after_crash(self):
        analyzer = PlayerAffectAnalyzer()
        analyzer.start()
        # Simulate crash by cancelling
        assert analyzer._task is not None
        analyzer._task.cancel()
        try:
            await analyzer._task
        except asyncio.CancelledError:
            pass
        assert analyzer._task is not None
        assert analyzer._task.done()
        # start() should detect done task and create new one
        analyzer.start()
        assert analyzer._task is not None
        assert not analyzer._task.done()
        await analyzer.stop()


# ---------------------------------------------------------------------------
# format_affect_context
# ---------------------------------------------------------------------------


class TestFormatAffectContext:
    def test_full_vector(self):
        vec = {
            "engagement": {
                "level": "high",
                "trend": "rising",
                "signals": ["long_utterance", "question_asked"],
            },
            "energy": {
                "speech_rate_wps": 3.2,
                "rate_vs_baseline": "+15%",
            },
            "interaction_style": {
                "mode": "exploratory",
                "signals": ["exploratory", "planning"],
            },
            "response_latency_ms": 1200,
            "latency_vs_baseline": "-20%",
            "turn_number": 14,
            "session_duration_min": 12.5,
            "calibration_confidence": "high",
        }
        result = format_affect_context(vec)
        assert "[Player Affect" in result
        assert "high" in result
        assert "rising" in result
        assert "exploratory" in result

    def test_minimal_vector(self):
        vec = {
            "engagement": {
                "level": "minimal",
                "trend": "falling",
                "signals": ["minimal_response"],
            },
            "energy": {
                "speech_rate_wps": None,
                "rate_vs_baseline": "n/a",
            },
            "interaction_style": {
                "mode": "passive",
                "signals": ["minimal"],
            },
            "response_latency_ms": 0,
            "latency_vs_baseline": "n/a",
            "turn_number": 1,
            "session_duration_min": 0.5,
            "calibration_confidence": "low",
        }
        result = format_affect_context(vec)
        assert "[Player Affect" in result
        assert "minimal" in result
        assert "passive" in result

    def test_low_calibration_note(self):
        vec = {
            "engagement": {
                "level": "moderate",
                "trend": "stable",
                "signals": [],
            },
            "energy": {
                "speech_rate_wps": 2.5,
                "rate_vs_baseline": "n/a",
            },
            "interaction_style": {
                "mode": "exploratory",
                "signals": [],
            },
            "response_latency_ms": 1000,
            "latency_vs_baseline": "n/a",
            "turn_number": 2,
            "session_duration_min": 1.0,
            "calibration_confidence": "low",
        }
        result = format_affect_context(vec)
        assert "calibrating" in result.lower() or "low confidence" in result.lower()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_speech_event(
    text: str,
    event_type: SpeechEventType = SpeechEventType.FINAL_TRANSCRIPT,
    words: list[TimedString] | None = None,
) -> SpeechEvent:
    """Create a mock SpeechEvent for testing."""
    if words is None and text.strip():
        # Generate simple timed words
        word_list = text.strip().split()
        words = []
        t = 0.0
        for w in word_list:
            words.append(TimedString(w, start_time=t, end_time=t + 0.3))
            t += 0.4

    speech_data = SpeechData(
        language=LanguageCode("en"),
        text=text,
        words=words,
    )
    return SpeechEvent(
        type=event_type,
        alternatives=[speech_data],
    )
