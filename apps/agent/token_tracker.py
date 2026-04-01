"""Token usage tracker — logs per-turn token metrics for cost monitoring."""

import logging
from dataclasses import dataclass

logger = logging.getLogger("divineruin.tokens")


@dataclass
class TokenTracker:
    """Accumulates token usage from AgentSession events."""

    total_input: int = 0
    total_output: int = 0
    total_cache_read: int = 0
    total_cache_write: int = 0
    turn_count: int = 0

    def on_metrics(self, metrics) -> None:
        """Handle metrics_collected event from AgentSession."""
        for llm_metric in getattr(metrics, "llm_metrics", []):
            input_tokens = getattr(llm_metric, "input_token_count", 0) or 0
            output_tokens = getattr(llm_metric, "output_token_count", 0) or 0
            cache_read = getattr(llm_metric, "cache_read_input_token_count", 0) or 0
            cache_write = getattr(llm_metric, "cache_creation_input_token_count", 0) or 0

            self.total_input += input_tokens
            self.total_output += output_tokens
            self.total_cache_read += cache_read
            self.total_cache_write += cache_write
            self.turn_count += 1

            logger.info(
                "Turn %d tokens: in=%d out=%d cache_read=%d cache_write=%d",
                self.turn_count,
                input_tokens,
                output_tokens,
                cache_read,
                cache_write,
            )

    def summary(self) -> dict:
        """Return accumulated token usage summary."""
        return {
            "turns": self.turn_count,
            "total_input": self.total_input,
            "total_output": self.total_output,
            "total_cache_read": self.total_cache_read,
            "total_cache_write": self.total_cache_write,
        }
