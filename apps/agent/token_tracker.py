"""Token usage tracker — logs per-turn token metrics for cost monitoring."""

import logging
from dataclasses import dataclass

logger = logging.getLogger("divineruin.tokens")


@dataclass
class TokenTracker:
    """Accumulates token usage from AgentSession `metrics_collected` events.

    NO CACHE-WRITE COUNTER, deliberately. livekit's LLMMetrics carries
    prompt_tokens / completion_tokens / prompt_cached_tokens and nothing else about
    caching — there is no cache-creation field to read. An earlier version kept a
    total_cache_write that no source could ever move; a counter that cannot change is
    the vacuous certification constraint 1 forbids, so it is gone rather than reported
    as a permanent 0.
    """

    total_input: int = 0
    total_output: int = 0
    total_cache_read: int = 0
    turn_count: int = 0

    def on_metrics(self, ev) -> None:
        """Handle a `metrics_collected` event from AgentSession.

        The event carries ONE metrics object on `.metrics` (livekit.agents.voice.events
        .MetricsCollectedEvent: type/metrics/created_at). It is not a collection, and it
        is not named `llm_metrics` — reading a `llm_metrics` list off it, as this did
        until bug 3aea2529, silently defaulted to [] and left every counter at 0 forever.
        The event fires for STT/TTS/EOU metrics too, so non-LLM payloads are skipped.
        """
        metric = getattr(ev, "metrics", None)
        if metric is None or getattr(metric, "type", None) != "llm_metrics":
            return

        input_tokens = metric.prompt_tokens or 0
        output_tokens = metric.completion_tokens or 0
        cache_read = metric.prompt_cached_tokens or 0

        self.total_input += input_tokens
        self.total_output += output_tokens
        self.total_cache_read += cache_read
        self.turn_count += 1

        logger.info(
            "Turn %d tokens: in=%d out=%d cache_read=%d",
            self.turn_count,
            input_tokens,
            output_tokens,
            cache_read,
        )

    def summary(self) -> dict:
        """Return accumulated token usage summary."""
        return {
            "turns": self.turn_count,
            "total_input": self.total_input,
            "total_output": self.total_output,
            "total_cache_read": self.total_cache_read,
        }
