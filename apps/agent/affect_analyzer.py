"""Player Affect Analyzer — Phase A: transcript-only baseline.

Computes a per-turn affect vector from Deepgram STT events (word timestamps,
utterance text, response latency). Runs as an independent async task that
never blocks the voice pipeline.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from collections import deque
from dataclasses import dataclass, field

from livekit.agents.stt import SpeechEvent, SpeechEventType, SpeechData
from livekit.agents.types import NOT_GIVEN, TimedString

logger = logging.getLogger("divineruin.affect")

# ---------------------------------------------------------------------------
# Pattern detection
# ---------------------------------------------------------------------------

_INTERROGATIVE_STARTERS = re.compile(
    r"^(who|what|where|when|why|how|is|are|do|does|did|can|could|would|should|will)\b",
    re.IGNORECASE,
)

_EXPLORATORY_PATTERNS = re.compile(
    r"\b(what if|i wonder|let me look|look around|investigate|examine|explore|search|check|inspect)\b",
    re.IGNORECASE,
)

_DECISIVE_PATTERNS = re.compile(
    r"\b(i attack|i cast|i open|i go|i run|i grab|i draw|i strike|i move|i pick up|i throw|i use|let's go|let's do)\b",
    re.IGNORECASE,
)

_SOCIAL_PATTERNS = re.compile(
    r"\b(talk to|speak with|ask (him|her|them)|tell (him|her|them)|hey |hello |hi )\b",
    re.IGNORECASE,
)

_CAUTIOUS_PATTERNS = re.compile(
    r"\b(is it safe|careful|trap|danger|wait a (moment|second|minute)|be careful|slowly|quietly|sneak)\b",
    re.IGNORECASE,
)

_CONFUSED_PATTERNS = re.compile(
    r"\b(wait what|what do you mean|i don'?t understand|huh\??|confused|say that again|repeat that|come again)\b",
    re.IGNORECASE,
)

_MINIMAL_RESPONSES = re.compile(
    r"^(ok|okay|sure|yeah|yep|yes|no|nah|uh huh|hmm|mhm|right|fine|got it|alright)\.?$",
    re.IGNORECASE,
)

_PLANNING_PATTERNS = re.compile(
    r"\b(i want to|we should|let's|i think we|maybe we|plan|first we|then we)\b",
    re.IGNORECASE,
)


def detect_question(text: str) -> bool:
    """Return True if the utterance is a question."""
    stripped = text.strip()
    if stripped.endswith("?"):
        return True
    if _INTERROGATIVE_STARTERS.search(stripped):
        return True
    return False


def detect_interaction_signals(text: str) -> list[str]:
    """Return a list of interaction signal tags found in the text."""
    signals: list[str] = []
    if _EXPLORATORY_PATTERNS.search(text):
        signals.append("exploratory")
    if _DECISIVE_PATTERNS.search(text):
        signals.append("decisive")
    if _SOCIAL_PATTERNS.search(text):
        signals.append("social")
    if _CAUTIOUS_PATTERNS.search(text):
        signals.append("cautious")
    if _CONFUSED_PATTERNS.search(text):
        signals.append("confused")
    if _MINIMAL_RESPONSES.match(text.strip()):
        signals.append("minimal")
    if _PLANNING_PATTERNS.search(text):
        signals.append("planning")
    if detect_question(text):
        signals.append("question")
    return signals


# ---------------------------------------------------------------------------
# Speech rate from TimedString word timestamps
# ---------------------------------------------------------------------------


def compute_speech_rate(words: list[TimedString]) -> float | None:
    """Words per second from TimedString timestamps.

    Returns None if timestamps are unavailable or duration is zero.
    """
    if not words:
        return None

    # Collect valid start/end times
    start_times: list[float] = []
    end_times: list[float] = []
    for w in words:
        st = getattr(w, "start_time", NOT_GIVEN)
        et = getattr(w, "end_time", NOT_GIVEN)
        if isinstance(st, float):
            start_times.append(st)
        if isinstance(et, float):
            end_times.append(et)

    if not start_times or not end_times:
        return None

    duration = max(end_times) - min(start_times)
    if duration <= 0:
        return None

    return len(words) / duration


# ---------------------------------------------------------------------------
# Engagement scoring
# ---------------------------------------------------------------------------

def compute_engagement_score(
    word_count: int,
    has_question: bool,
    signals: list[str],
    speech_rate: float | None,
    baseline_speech_rate: float | None,
) -> float:
    """Compute a 0-1 engagement score from per-turn metrics."""
    score = 0.0

    # Word count contribution (0-0.3)
    if word_count >= 15:
        score += 0.3
    elif word_count >= 8:
        score += 0.2
    elif word_count >= 3:
        score += 0.1
    # 1-2 words = 0

    # Question asked (0-0.15)
    if has_question:
        score += 0.15

    # Active interaction signals (0-0.3)
    active_signals = {"exploratory", "decisive", "social", "planning"}
    active_count = sum(1 for s in signals if s in active_signals)
    score += min(active_count * 0.15, 0.3)

    # Minimal/passive response penalty (-0.15)
    if "minimal" in signals:
        score -= 0.15

    # Confused adds a small amount (engagement, just frustrated)
    if "confused" in signals:
        score += 0.05

    # Speech rate contribution (0-0.25)
    if speech_rate is not None:
        if baseline_speech_rate and baseline_speech_rate > 0:
            rate_ratio = speech_rate / baseline_speech_rate
            if rate_ratio >= 1.15:
                score += 0.25
            elif rate_ratio >= 0.9:
                score += 0.15
            else:
                score += 0.05
        else:
            # No baseline yet — use absolute thresholds
            if speech_rate >= 3.0:
                score += 0.2
            elif speech_rate >= 2.0:
                score += 0.1

    return max(0.0, min(1.0, score))


def engagement_level(score: float) -> str:
    """Map a 0-1 score to a discrete engagement level."""
    if score >= 0.6:
        return "high"
    if score >= 0.35:
        return "moderate"
    if score >= 0.15:
        return "low"
    return "minimal"


def classify_interaction_mode(signals: list[str]) -> str:
    """Pick the dominant interaction mode from detected signals."""
    priority = ["confused", "exploratory", "decisive", "social", "cautious"]
    for mode in priority:
        if mode in signals:
            return mode
    if "minimal" in signals:
        return "passive"
    return "exploratory"  # default when nothing matches


def compute_engagement_trend(recent_scores: deque[float] | list[float]) -> str:
    """Compute trend from last N engagement scores.

    Returns 'rising', 'falling', or 'stable'. Needs at least 3 data points.
    """
    if len(recent_scores) < 3:
        return "stable"

    scores = list(recent_scores)
    mid = len(scores) // 2
    first_half = sum(scores[:mid]) / mid
    second_half = sum(scores[mid:]) / (len(scores) - mid)
    diff = second_half - first_half

    if diff > 0.1:
        return "rising"
    if diff < -0.1:
        return "falling"
    return "stable"


def format_vs_baseline(current: float | None, baseline: float | None) -> str:
    """Format a metric vs baseline as a signed percentage string."""
    if current is None or baseline is None or baseline <= 0:
        return "n/a"
    if not (math.isfinite(current) and math.isfinite(baseline)):
        return "n/a"
    pct = ((current - baseline) / baseline) * 100
    if pct >= 0:
        return f"+{pct:.0f}%"
    return f"{pct:.0f}%"


# ---------------------------------------------------------------------------
# Turn data
# ---------------------------------------------------------------------------

@dataclass
class TurnData:
    """Metrics collected for a single player turn."""
    word_count: int = 0
    speech_rate: float | None = None
    has_question: bool = False
    signals: list[str] = field(default_factory=list)
    engagement_score: float = 0.0
    response_latency_ms: int = 0
    timestamp: float = 0.0


# ---------------------------------------------------------------------------
# PlayerAffectAnalyzer
# ---------------------------------------------------------------------------


class PlayerAffectAnalyzer:
    """Transcript-based player affect analyzer (Phase A).

    Consumes SpeechEvent objects via an asyncio.Queue and computes a
    per-turn affect vector. Designed to run fully parallel to the voice
    pipeline — never blocks STT→LLM→TTS.
    """

    def __init__(self, window_size: int = 5) -> None:
        self._stt_event_queue: asyncio.Queue[SpeechEvent] = asyncio.Queue(maxsize=10)
        self._current_vector: dict | None = None
        self._task: asyncio.Task | None = None

        # Turn history
        self._turns: deque[TurnData] = deque(maxlen=50)
        self._recent_scores: deque[float] = deque(maxlen=window_size)

        # Baselines (running sums for O(1) average computation)
        self._rate_sum: float = 0.0
        self._rate_count: int = 0
        self._latency_sum: float = 0.0
        self._latency_count: int = 0
        self._turn_count: int = 0

        # TTS end tracking for response latency
        self._last_tts_end: float | None = None

        # Session start
        self._session_start: float = time.time()

    def enqueue_event(self, event: SpeechEvent) -> None:
        """Non-blocking enqueue of a SpeechEvent. Drops on full queue."""
        try:
            self._stt_event_queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.debug("Affect analyzer queue full, dropping event")

    def start(self) -> None:
        """Start the background processing task."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Cancel the background task and wait for it to finish."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        """Background loop — consume STT events from queue."""
        try:
            while True:
                try:
                    event = await asyncio.wait_for(
                        self._stt_event_queue.get(), timeout=0.5
                    )
                    self._process_stt_event(event)
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Affect analyzer task crashed")

    def _process_stt_event(self, event: SpeechEvent) -> None:
        """Process a single SpeechEvent and update the affect vector."""
        if event.type != SpeechEventType.FINAL_TRANSCRIPT:
            return

        if not event.alternatives:
            return

        speech_data: SpeechData = event.alternatives[0]
        text = speech_data.text.strip()
        if not text:
            return

        words = speech_data.words or []
        word_count = len(text.split())
        speech_rate = compute_speech_rate(words)
        has_question = detect_question(text)
        signals = detect_interaction_signals(text)

        # Response latency (monotonic clock: TTS end → now)
        latency_ms = 0
        if self._last_tts_end is not None:
            latency_s = time.monotonic() - self._last_tts_end
            latency_ms = max(0, min(30_000, int(latency_s * 1000)))

        self._turn_count += 1

        # Update running baselines
        if speech_rate is not None:
            self._rate_sum += speech_rate
            self._rate_count += 1
        if latency_ms > 0:
            self._latency_sum += float(latency_ms)
            self._latency_count += 1

        baseline_rate = self._rate_sum / self._rate_count if self._rate_count else None
        baseline_latency = self._latency_sum / self._latency_count if self._latency_count else None

        score = compute_engagement_score(
            word_count=word_count,
            has_question=has_question,
            signals=signals,
            speech_rate=speech_rate,
            baseline_speech_rate=baseline_rate,
        )

        turn = TurnData(
            word_count=word_count,
            speech_rate=speech_rate,
            has_question=has_question,
            signals=signals,
            engagement_score=score,
            response_latency_ms=latency_ms,
            timestamp=time.time(),
        )
        self._turns.append(turn)
        self._recent_scores.append(score)

        # Calibration confidence
        if self._turn_count <= 2:
            calibration = "low"
        elif self._turn_count <= 4:
            calibration = "medium"
        else:
            calibration = "high"

        level = engagement_level(score)
        trend = compute_engagement_trend(self._recent_scores)
        mode = classify_interaction_mode(signals)

        # Build engagement signals list
        engagement_signals: list[str] = []
        if word_count >= 15:
            engagement_signals.append("long_utterance")
        elif word_count <= 3:
            engagement_signals.append("short_utterance")
        if has_question:
            engagement_signals.append("question_asked")
        if "planning" in signals:
            engagement_signals.append("planning_language")
        if "minimal" in signals:
            engagement_signals.append("minimal_response")

        session_min = (time.time() - self._session_start) / 60.0

        self._current_vector = {
            "engagement": {
                "level": level,
                "trend": trend,
                "signals": engagement_signals,
            },
            "energy": {
                "speech_rate_wps": round(speech_rate, 1) if speech_rate else None,
                "rate_vs_baseline": format_vs_baseline(speech_rate, baseline_rate),
            },
            "interaction_style": {
                "mode": mode,
                "signals": [s for s in signals if s != "question"],
            },
            "response_latency_ms": latency_ms,
            "latency_vs_baseline": format_vs_baseline(float(latency_ms), baseline_latency),
            "turn_number": self._turn_count,
            "session_duration_min": round(session_min, 1),
            "calibration_confidence": calibration,
        }

    def get_current_vector(self) -> dict | None:
        """Non-blocking read of the latest affect vector."""
        return self._current_vector

    def record_tts_end(self) -> None:
        """Called when the DM finishes speaking (TTS output complete)."""
        self._last_tts_end = time.monotonic()
