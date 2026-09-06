"""Token usage tracker — logs per-request token metrics for cost monitoring."""

import logging
from dataclasses import dataclass, field

from livekit.agents import llm

logger = logging.getLogger("divineruin.tokens")


@dataclass
class TokenTracker:
    """Accumulates token usage from the provider's own `llm.CompletionUsage`.

    Fed from the final ChatChunk in `BaseGameAgent.llm_node`, not from `metrics_collected`:
    livekit builds `LLMMetrics` from this very usage object and drops `cache_creation_tokens`
    on the way (llm/llm.py:325-331), and that field is the one that says whether a request
    REWROTE the cached prefix or read it. `cache_writes` is per REQUEST, not per player turn:
    `max_tool_steps` lets one turn fan out into several requests, and a running total cannot
    tell round 3 from round 1.
    """

    total_input: int = 0
    total_output: int = 0
    total_cache_read: int = 0
    cache_writes: list[int] = field(default_factory=list)
    request_count: int = 0

    def on_usage(self, usage: llm.CompletionUsage) -> None:
        """Record one LLM request from the usage the provider reported."""
        self.total_input += usage.prompt_tokens
        self.total_output += usage.completion_tokens
        self.total_cache_read += usage.prompt_cached_tokens
        self.cache_writes.append(usage.cache_creation_tokens)
        self.request_count += 1

        logger.info(
            "Request %d tokens: in=%d out=%d cache_read=%d cache_write=%d",
            self.request_count,
            usage.prompt_tokens,
            usage.completion_tokens,
            usage.prompt_cached_tokens,
            usage.cache_creation_tokens,
        )

    def summary(self) -> dict:
        """Return accumulated token usage summary."""
        return {
            "requests": self.request_count,
            "total_input": self.total_input,
            "total_output": self.total_output,
            "total_cache_read": self.total_cache_read,
            # Derived, never a second accumulator: two representations of one fact drift the
            # moment an edit touches only one of them.
            "total_cache_write": sum(self.cache_writes),
        }
