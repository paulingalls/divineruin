"""TokenTracker reads the provider's own usage — including the cache WRITE.

REAL livekit types, never MagicMock (constraint 9). Bug 3aea2529 survived because the old
tests built a MagicMock and set an attribute on it: the mock invented whatever production
asked for, so the suite passed against a payload shape that does not exist and every counter
sat at 0 in production. Both sides of this contract are the real thing here.

The source is `llm.CompletionUsage` off the final ChatChunk, not `metrics_collected`:
`LLMMetrics` is built from that very usage object and drops `cache_creation_tokens`
(livekit/agents/llm/llm.py:325-331), which is the one number story-024's cost claim rests on.
"""

from unittest.mock import MagicMock, patch

from livekit.agents.llm import ChatChunk, CompletionUsage

from combat_agent import CombatAgent
from session_data import SessionData
from token_tracker import TokenTracker


def _usage(*, prompt: int = 100, completion: int = 50, cached: int = 0, cache_write: int = 0) -> CompletionUsage:
    return CompletionUsage(
        completion_tokens=completion,
        prompt_tokens=prompt,
        prompt_cached_tokens=cached,
        cache_creation_tokens=cache_write,
        cache_read_tokens=cached,
        total_tokens=prompt + completion,
    )


class TestTokenTracker:
    def test_accumulates_one_request(self):
        tracker = TokenTracker()
        tracker.on_usage(_usage(prompt=100, completion=50, cached=80))

        summary = tracker.summary()
        assert summary["requests"] == 1
        assert summary["total_input"] == 100
        assert summary["total_output"] == 50
        assert summary["total_cache_read"] == 80

    def test_accumulates_multiple_requests(self):
        tracker = TokenTracker()
        for _i in range(3):
            tracker.on_usage(_usage(prompt=100, completion=50, cached=80))

        summary = tracker.summary()
        assert summary["requests"] == 3
        assert summary["total_input"] == 300
        assert summary["total_cache_read"] == 240

    def test_records_cache_write_from_the_provider_usage(self):
        tracker = TokenTracker()
        tracker.on_usage(_usage(cache_write=7000))

        assert tracker.summary()["total_cache_write"] == 7000
        assert tracker.cache_writes == [7000]

    def test_per_request_cache_writes_are_kept_in_order(self):
        """Per request, not aggregate: the claim story-024 measures is that a round does not
        rewrite the prefix, and a running total cannot tell round 3 from round 1."""
        tracker = TokenTracker()
        for write in (7000, 0, 120):
            tracker.on_usage(_usage(cache_write=write))

        assert tracker.cache_writes == [7000, 0, 120]
        assert tracker.summary()["total_cache_write"] == 7120


class TestLlmNodeTap:
    """The seam that actually matters — writer and reader both real.

    A tracker test and an llm_node test that each mocked their own half would agree with each
    other and with nothing else (feedback_contract_both_sides_mocked).
    """

    async def test_llm_node_forwards_the_chunk_usage_to_the_session_tracker(self):
        sd = SessionData(player_id="p1", location_id="accord_guild_hall")
        agent = CombatAgent()
        session = MagicMock()
        session.userdata = sd

        async def _fake_default(_agent, _chat_ctx, _tools, _model_settings):
            yield ChatChunk(id="chunk-1")
            yield ChatChunk(id="chunk-2", usage=_usage(prompt=900, completion=40, cached=800, cache_write=1200))

        with (
            patch.object(type(agent), "session", new_callable=lambda: property(lambda self: session)),
            patch("livekit.agents.Agent.default.llm_node", _fake_default),
        ):
            chunks = [chunk async for chunk in agent.llm_node(MagicMock(), [], MagicMock())]

        assert len(chunks) == 2  # every chunk still reaches the pipeline
        assert sd.tokens.cache_writes == [1200]
        assert sd.tokens.summary()["total_input"] == 900
