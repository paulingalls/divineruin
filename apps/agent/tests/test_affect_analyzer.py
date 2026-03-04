"""Tests for the Player Affect Analyzer (Phase A: transcript-only)."""

import asyncio
import time

import pytest

from affect_analyzer import (
    PlayerAffectAnalyzer,
    TurnData,
    compute_engagement_score,
    compute_engagement_trend,
    compute_speech_rate,
    classify_interaction_mode,
    detect_interaction_signals,
    detect_question,
    engagement_level,
    format_vs_baseline,
)
from prompts import format_affect_context
from livekit.agents.stt import SpeechEvent, SpeechEventType, SpeechData
from livekit.agents.types import TimedString, NOT_GIVEN


# ---------------------------------------------------------------------------
# Question detection
# ---------------------------------------------------------------------------

class TestDetectQuestion:
    def test_question_mark(self):
        assert detect_question("Where is the blacksmith?") is True

    def test_interrogative_starter(self):
        assert detect_question("Who lives in the tower") is True

    def test_how_starter(self):
        assert detect_question("How do I get there") is True

    def test_not_a_question(self):
        assert detect_question("I open the door.") is False

    def test_statement_starting_with_i(self):
        assert detect_question("I want to go north") is False

    def test_does_starter(self):
        assert detect_question("Does anyone know the way") is True

    def test_empty_string(self):
        assert detect_question("") is False


# ---------------------------------------------------------------------------
# Interaction signal detection
# ---------------------------------------------------------------------------

class TestDetectInteractionSignals:
    def test_exploratory(self):
        signals = detect_interaction_signals("I want to look around the room")
        assert "exploratory" in signals

    def test_decisive(self):
        signals = detect_interaction_signals("I attack the goblin")
        assert "decisive" in signals

    def test_social(self):
        signals = detect_interaction_signals("I want to talk to the merchant")
        assert "social" in signals

    def test_cautious(self):
        signals = detect_interaction_signals("Is it safe to go in there?")
        assert "cautious" in signals

    def test_confused(self):
        signals = detect_interaction_signals("Wait what? I don't understand")
        assert "confused" in signals

    def test_minimal(self):
        signals = detect_interaction_signals("ok")
        assert "minimal" in signals

    def test_minimal_with_period(self):
        signals = detect_interaction_signals("sure.")
        assert "minimal" in signals

    def test_planning(self):
        signals = detect_interaction_signals("I think we should go to the tower first")
        assert "planning" in signals

    def test_question_signal(self):
        signals = detect_interaction_signals("Where is the blacksmith?")
        assert "question" in signals

    def test_no_signals_in_normal_speech(self):
        signals = detect_interaction_signals("The weather is nice today")
        assert signals == []

    def test_multiple_signals(self):
        signals = detect_interaction_signals("What if we investigate the cave?")
        assert "exploratory" in signals
        assert "question" in signals


# ---------------------------------------------------------------------------
# Speech rate computation
# ---------------------------------------------------------------------------

class TestComputeSpeechRate:
    def test_normal_speech(self):
        words = [
            TimedString("hello", start_time=0.0, end_time=0.3),
            TimedString("world", start_time=0.4, end_time=0.7),
            TimedString("how", start_time=0.8, end_time=1.0),
            TimedString("are", start_time=1.1, end_time=1.3),
            TimedString("you", start_time=1.4, end_time=1.6),
        ]
        rate = compute_speech_rate(words)
        assert rate is not None
        # 5 words over 1.6 seconds = 3.125 wps
        assert abs(rate - 3.125) < 0.01

    def test_single_word(self):
        words = [TimedString("hello", start_time=0.0, end_time=0.5)]
        rate = compute_speech_rate(words)
        # 1 word / 0.5s = 2.0
        assert rate is not None
        assert abs(rate - 2.0) < 0.01

    def test_zero_duration(self):
        words = [
            TimedString("hi", start_time=1.0, end_time=1.0),
        ]
        rate = compute_speech_rate(words)
        assert rate is None

    def test_no_timestamps(self):
        words = [
            TimedString("hello"),
            TimedString("world"),
        ]
        rate = compute_speech_rate(words)
        assert rate is None

    def test_empty_list(self):
        assert compute_speech_rate([]) is None

    def test_mixed_timestamps(self):
        # Some words have times, some don't — should still work with available data
        words = [
            TimedString("hello", start_time=0.0, end_time=0.3),
            TimedString("um"),  # no timestamps
            TimedString("world", start_time=0.8, end_time=1.1),
        ]
        rate = compute_speech_rate(words)
        assert rate is not None
        # 3 words over 1.1s
        assert abs(rate - 3 / 1.1) < 0.01


# ---------------------------------------------------------------------------
# Engagement score computation
# ---------------------------------------------------------------------------

class TestComputeEngagementScore:
    def test_high_engagement(self):
        score = compute_engagement_score(
            word_count=20,
            has_question=True,
            signals=["exploratory", "planning", "question"],
            speech_rate=3.5,
            baseline_speech_rate=2.5,
        )
        assert score >= 0.6

    def test_minimal_engagement(self):
        score = compute_engagement_score(
            word_count=1,
            has_question=False,
            signals=["minimal"],
            speech_rate=1.0,
            baseline_speech_rate=2.5,
        )
        assert score < 0.2

    def test_moderate_engagement(self):
        score = compute_engagement_score(
            word_count=10,
            has_question=False,
            signals=["decisive"],
            speech_rate=2.5,
            baseline_speech_rate=2.5,
        )
        assert 0.3 <= score <= 0.7

    def test_score_clamped_to_0_1(self):
        # Even with many signals, should not exceed 1.0
        score = compute_engagement_score(
            word_count=50,
            has_question=True,
            signals=["exploratory", "decisive", "social", "planning", "question"],
            speech_rate=5.0,
            baseline_speech_rate=2.0,
        )
        assert score <= 1.0

    def test_no_baseline_uses_absolute(self):
        score = compute_engagement_score(
            word_count=10,
            has_question=False,
            signals=[],
            speech_rate=3.5,
            baseline_speech_rate=None,
        )
        assert score > 0


# ---------------------------------------------------------------------------
# Engagement level from score
# ---------------------------------------------------------------------------

class TestEngagementLevel:
    def test_high(self):
        assert engagement_level(0.8) == "high"

    def test_high_boundary(self):
        assert engagement_level(0.6) == "high"

    def test_moderate(self):
        assert engagement_level(0.5) == "moderate"

    def test_moderate_boundary(self):
        assert engagement_level(0.35) == "moderate"

    def test_low(self):
        assert engagement_level(0.25) == "low"

    def test_low_boundary(self):
        assert engagement_level(0.15) == "low"

    def test_minimal(self):
        assert engagement_level(0.1) == "minimal"

    def test_zero(self):
        assert engagement_level(0.0) == "minimal"


# ---------------------------------------------------------------------------
# Interaction mode classification
# ---------------------------------------------------------------------------

class TestClassifyInteractionMode:
    def test_exploratory(self):
        assert classify_interaction_mode(["exploratory", "question"]) == "exploratory"

    def test_decisive(self):
        assert classify_interaction_mode(["decisive"]) == "decisive"

    def test_confused_takes_priority(self):
        assert classify_interaction_mode(["confused", "exploratory"]) == "confused"

    def test_social(self):
        assert classify_interaction_mode(["social"]) == "social"

    def test_passive_from_minimal(self):
        assert classify_interaction_mode(["minimal"]) == "passive"

    def test_default_exploratory(self):
        assert classify_interaction_mode([]) == "exploratory"

    def test_cautious(self):
        assert classify_interaction_mode(["cautious"]) == "cautious"


# ---------------------------------------------------------------------------
# Engagement trend
# ---------------------------------------------------------------------------

class TestComputeEngagementTrend:
    def test_rising(self):
        scores = [0.2, 0.3, 0.4, 0.5, 0.6]
        assert compute_engagement_trend(scores) == "rising"

    def test_falling(self):
        scores = [0.7, 0.6, 0.5, 0.3, 0.2]
        assert compute_engagement_trend(scores) == "falling"

    def test_stable(self):
        scores = [0.5, 0.5, 0.5, 0.5, 0.5]
        assert compute_engagement_trend(scores) == "stable"

    def test_insufficient_data(self):
        assert compute_engagement_trend([0.5, 0.6]) == "stable"

    def test_empty(self):
        assert compute_engagement_trend([]) == "stable"

    def test_three_points_rising(self):
        # [0.2] vs [0.5, 0.7] → avg 0.2 vs 0.6 → rising
        assert compute_engagement_trend([0.2, 0.5, 0.7]) == "rising"


# ---------------------------------------------------------------------------
# Metric vs baseline formatting
# ---------------------------------------------------------------------------

class TestFormatVsBaseline:
    def test_positive(self):
        assert format_vs_baseline(3.0, 2.5) == "+20%"

    def test_negative(self):
        assert format_vs_baseline(2.0, 2.5) == "-20%"

    def test_zero_baseline(self):
        assert format_vs_baseline(3.0, 0.0) == "n/a"

    def test_none_current(self):
        assert format_vs_baseline(None, 2.5) == "n/a"

    def test_none_baseline(self):
        assert format_vs_baseline(3.0, None) == "n/a"

    def test_latency_positive(self):
        assert format_vs_baseline(1500.0, 1000.0) == "+50%"

    def test_latency_negative(self):
        assert format_vs_baseline(800.0, 1000.0) == "-20%"

    def test_latency_no_baseline(self):
        assert format_vs_baseline(1000.0, None) == "n/a"

    def test_inf_current(self):
        assert format_vs_baseline(float("inf"), 2.5) == "n/a"

    def test_inf_baseline(self):
        assert format_vs_baseline(3.0, float("inf")) == "n/a"

    def test_nan_current(self):
        assert format_vs_baseline(float("nan"), 2.5) == "n/a"

    def test_nan_baseline(self):
        assert format_vs_baseline(3.0, float("nan")) == "n/a"


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
        analyzer._task.cancel()
        try:
            await analyzer._task
        except asyncio.CancelledError:
            pass
        assert analyzer._task.done()
        # start() should detect done task and create new one
        analyzer.start()
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
        language="en",
        text=text,
        words=words,
    )
    return SpeechEvent(
        type=event_type,
        alternatives=[speech_data],
    )
