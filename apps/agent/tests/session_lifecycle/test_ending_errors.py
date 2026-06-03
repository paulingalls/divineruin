"""Tests for the end_session tool, session-ending prompt, LLM error handling, transcript path."""

import json
from unittest.mock import MagicMock, patch

import pytest
from session_lifecycle._helpers import _make_context


class TestEndSessionTool:
    """Test end_session tool."""

    @pytest.mark.asyncio
    async def test_sets_ending_requested(self):
        from session_tools import end_session

        ctx = _make_context()
        ctx.userdata.session_xp_earned = 100
        ctx.userdata.session_items_found = ["Sword"]
        result = json.loads(await end_session._func(ctx, reason="player wants to stop"))
        assert result["status"] == "ending"
        assert ctx.userdata.ending_requested is True

    @pytest.mark.asyncio
    async def test_returns_session_stats(self):
        from session_tools import end_session

        ctx = _make_context()
        ctx.userdata.session_xp_earned = 75
        ctx.userdata.session_items_found = ["Shield", "Potion"]
        ctx.userdata.session_quests_progressed = ["quest_1"]
        ctx.userdata.session_locations_visited = ["loc_a", "loc_b"]
        result = json.loads(await end_session._func(ctx, reason="goodbye"))
        stats = result["session_stats"]
        assert stats["xp_earned"] == 75
        assert stats["items_found"] == ["Shield", "Potion"]
        assert stats["quests_progressed"] == ["quest_1"]
        assert stats["locations_visited"] == ["loc_a", "loc_b"]

    @pytest.mark.asyncio
    async def test_includes_narrative_instruction(self):
        from session_tools import end_session

        ctx = _make_context()
        result = json.loads(await end_session._func(ctx, reason="need to go"))
        assert "instruction" in result
        assert "wrap-up" in result["instruction"].lower()


class TestSessionEndingPrompt:
    """Test that system prompt includes session ending instructions."""

    def test_system_prompt_contains_session_ending(self):
        from system_prompts import build_system_prompt

        prompt = build_system_prompt("test_location")
        assert "Session Ending" in prompt
        assert "end_session" in prompt

    def test_end_session_in_city_tools(self):
        from city_agent import CITY_TOOLS
        from session_tools import end_session

        assert end_session in CITY_TOOLS


class TestLLMErrorHandling:
    """Test llm_node retry and fallback."""

    @pytest.mark.asyncio
    async def test_fallback_on_repeated_failure(self):
        from creation_agent import CreationAgent

        agent = CreationAgent()

        mock_chat_ctx = MagicMock()
        mock_tools = []
        mock_settings = MagicMock()

        call_count = 0

        async def _failing_llm_node(self_agent, ctx, tools, settings):
            nonlocal call_count
            call_count += 1
            raise Exception("API timeout")
            # Make this an async generator
            yield  # pragma: no cover

        with patch("base_agent.Agent.default") as mock_default:
            mock_default.llm_node = _failing_llm_node

            chunks = []
            async for chunk in agent.llm_node(mock_chat_ctx, mock_tools, mock_settings):
                chunks.append(chunk)

        assert call_count == 3  # initial + 2 retries
        assert len(chunks) == 1
        assert "threads of fate" in chunks[0].lower()

    @pytest.mark.asyncio
    async def test_success_on_first_try(self):
        from creation_agent import CreationAgent

        agent = CreationAgent()

        mock_chat_ctx = MagicMock()
        mock_tools = []
        mock_settings = MagicMock()

        async def _success_llm_node(self_agent, ctx, tools, settings):
            yield "Hello adventurer"

        with patch("base_agent.Agent.default") as mock_default:
            mock_default.llm_node = _success_llm_node

            chunks = []
            async for chunk in agent.llm_node(mock_chat_ctx, mock_tools, mock_settings):
                chunks.append(chunk)

        assert chunks == ["Hello adventurer"]

    @pytest.mark.asyncio
    async def test_succeeds_after_retry(self):
        from creation_agent import CreationAgent

        agent = CreationAgent()

        mock_chat_ctx = MagicMock()
        mock_tools = []
        mock_settings = MagicMock()

        call_count = 0

        async def _flaky_llm_node(self_agent, ctx, tools, settings):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("Temporary error")
            yield "Recovered response"

        with patch("base_agent.Agent.default") as mock_default:
            mock_default.llm_node = _flaky_llm_node

            chunks = []
            async for chunk in agent.llm_node(mock_chat_ctx, mock_tools, mock_settings):
                chunks.append(chunk)

        assert call_count == 2
        assert chunks == ["Recovered response"]

    @pytest.mark.asyncio
    async def test_mid_stream_failure_does_not_retry(self):
        """If chunks were already yielded, don't retry (would produce garbled output)."""
        from creation_agent import CreationAgent

        agent = CreationAgent()

        mock_chat_ctx = MagicMock()
        mock_tools = []
        mock_settings = MagicMock()

        call_count = 0

        async def _mid_stream_fail(self_agent, ctx, tools, settings):
            nonlocal call_count
            call_count += 1
            yield "You see a"
            raise Exception("Connection reset")

        with patch("base_agent.Agent.default") as mock_default:
            mock_default.llm_node = _mid_stream_fail

            chunks = []
            async for chunk in agent.llm_node(mock_chat_ctx, mock_tools, mock_settings):
                chunks.append(chunk)

        assert call_count == 1  # No retry after partial yield
        assert chunks == ["You see a"]


class TestTranscriptLogPath:
    """Test transcript.py log_path accessor."""

    def test_log_path_returns_path(self):
        from transcript import TranscriptLogger

        tl = TranscriptLogger(room=None, log_path="/tmp/test_session.log")
        assert tl.log_path == "/tmp/test_session.log"
        tl.close()

    def test_log_path_default(self):
        from transcript import TranscriptLogger

        tl = TranscriptLogger(room=None)
        assert tl.log_path is not None
        assert "session_" in tl.log_path
        tl.close()
