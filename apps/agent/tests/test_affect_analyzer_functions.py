"""Tests for the Player Affect Analyzer pure functions (Phase A: transcript-only).

The stateless scoring/classification helpers — split from the stateful
PlayerAffectAnalyzer tests (test_affect_analyzer_analyzer.py) to keep each file
under the 500-line cap.
"""

from livekit.agents.types import TimedString

from affect_analyzer import (
    classify_interaction_mode,
    compute_engagement_score,
    compute_engagement_trend,
    compute_speech_rate,
    detect_interaction_signals,
    detect_question,
    engagement_level,
    format_vs_baseline,
)

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
