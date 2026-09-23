"""Tests for the end_session tool, session-ending prompt, LLM error handling, transcript path."""

import asyncio
import json
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from livekit.agents import Agent, AgentSession, ModelSettings, function_tool, llm
from livekit.agents.llm import ChatChunk, ChoiceDelta, CompletionUsage, FallbackAdapter, FunctionToolCall, ToolContext
from livekit.agents.voice.generation import perform_llm_inference
from livekit.agents.voice.speech_handle import SpeechHandle
from session_lifecycle._helpers import _make_context

from base_agent import _player_interrupted
from gameplay_llm import LUNA_MODEL, create_gameplay_llm
from session_data import SessionData

UNRESOLVED = "threads of fate"


def _usage() -> CompletionUsage:
    return CompletionUsage(completion_tokens=4, prompt_tokens=10, total_tokens=14)


def _agent_with_speech(speech) -> Agent:
    """An agent stub exposing only what the gate reads — no invented attributes."""
    return cast(Agent, SimpleNamespace(session=SimpleNamespace(current_speech=speech)))


def _pilot_session(selected_llm=None):
    session = MagicMock()
    session.userdata = SessionData(player_id="player", location_id="place")
    session.llm = selected_llm if selected_llm is not None else SimpleNamespace(model=LUNA_MODEL)
    return session


async def _pilot_chunks(agent, stream, *, interrupted=False, selected_llm=None):
    session = _pilot_session(selected_llm)
    with (
        patch.object(type(agent), "session", new_callable=lambda: property(lambda self: session)),
        patch("base_agent.Agent.default.llm_node", stream),
        patch("base_agent._player_interrupted", return_value=interrupted),
    ):
        chunks = [chunk async for chunk in agent.llm_node(MagicMock(), [], MagicMock())]
    return chunks, session.userdata


class TestEndSessionTool:
    """Test end_session tool."""

    @pytest.mark.asyncio
    async def test_returns_ending_status(self):
        from session_tools import end_session

        ctx = _make_context()
        ctx.userdata.session_xp_earned = 100
        ctx.userdata.session_items_found = ["Sword"]
        result = json.loads(await end_session._func(ctx, reason="player wants to stop"))
        assert result["status"] == "ending"

    @pytest.mark.asyncio
    async def test_returns_session_stats(self):
        from session_tools import end_session

        ctx = _make_context()
        sd = ctx.userdata
        # Session-wide tallies a departed host left behind; the last member's stats ignore them.
        sd.session_xp_earned = 500
        sd.session_items_found = ["Host sword"]
        sd.record_player_metric(sd.primary_player_id, "xp_earned", 75)
        for item in ("Shield", "Potion"):
            sd.record_player_metric(sd.primary_player_id, "items_found", item)
        sd.record_player_metric(sd.primary_player_id, "quest_progress", "quest_1")
        for loc in ("loc_a", "loc_b"):
            sd.record_player_metric(sd.primary_player_id, "locations_visited", loc)
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

    def test_end_session_in_exploration_tools(self):
        from exploration_agent import EXPLORATION_TOOLS
        from session_tools import end_session

        assert end_session in EXPLORATION_TOOLS


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


class TestLunaAtomicTurns:
    @pytest.mark.asyncio
    async def test_factory_luna_wrapped_by_livekit_still_uses_atomic_gate(self, monkeypatch):
        from creation_agent import CreationAgent

        async def stream(_agent, _ctx, _tools, _settings):
            yield ChatChunk(id="partial", delta=ChoiceDelta(content="The unfinished"))
            raise RuntimeError("provider failed after output")

        monkeypatch.setenv("GAMEPLAY_LLM", "openai-luna")
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        selected = create_gameplay_llm("unused")
        wrapped = FallbackAdapter([selected])
        try:
            chunks, _ = await _pilot_chunks(CreationAgent(), stream, selected_llm=wrapped)
        finally:
            await selected.aclose()

        assert len(chunks) == 1
        assert UNRESOLVED in chunks[0].lower()

    @pytest.mark.asyncio
    async def test_agent_luna_override_takes_precedence_over_session_llm(self, monkeypatch):
        from creation_agent import CreationAgent

        async def stream(_agent, _ctx, _tools, _settings):
            yield ChatChunk(id="partial", delta=ChoiceDelta(content="The unfinished"))
            raise RuntimeError("provider failed after output")

        monkeypatch.setenv("GAMEPLAY_LLM", "openai-luna")
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        selected = create_gameplay_llm("unused")
        agent = CreationAgent()
        agent.update_options(llm=selected)
        try:
            chunks, _ = await _pilot_chunks(agent, stream, selected_llm=SimpleNamespace(model="claude"))
        finally:
            await selected.aclose()

        assert len(chunks) == 1
        assert UNRESOLVED in chunks[0].lower()

    @pytest.mark.parametrize(
        "source,expected",
        [("user_turn", True), ("audio_activity", True), ("programmatic", False)],
    )
    @pytest.mark.asyncio
    async def test_only_player_sources_are_interruptions(self, source, expected):
        speech = SpeechHandle.create().interrupt(source=source)

        assert _player_interrupted(_agent_with_speech(speech)) is expected

    def test_a_turn_with_no_speech_or_no_session_is_not_an_interruption(self):
        class _Detached:
            @property
            def session(self):
                raise RuntimeError("Agent isn't running")

        assert _player_interrupted(_agent_with_speech(None)) is False
        assert _player_interrupted(cast(Agent, _Detached())) is False

    def test_the_speech_state_the_gate_reads_is_livekit_public_api(self):
        """A rename of `current_speech` would otherwise read as green off the stub above."""
        assert isinstance(AgentSession.current_speech, property)

    @pytest.mark.parametrize("preamble", [False, True], ids=["no-preamble", "preamble"])
    @pytest.mark.asyncio
    async def test_provider_error_discards_partial_output_and_reports_failure(self, preamble):
        from creation_agent import CreationAgent

        async def stream(_agent, _ctx, _tools, _settings):
            if preamble:
                yield ChatChunk(id="partial", delta=ChoiceDelta(content="I reach for fate"))
            raise RuntimeError("OpenAI 400")

        chunks, _ = await _pilot_chunks(CreationAgent(), stream)

        assert len(chunks) == 1
        assert UNRESOLVED in chunks[0].lower()

    @pytest.mark.asyncio
    async def test_truncation_discards_output_and_reports_failure(self):
        from creation_agent import CreationAgent

        async def stream(_agent, _ctx, _tools, _settings):
            yield ChatChunk(id="partial", delta=ChoiceDelta(content="The unfinished"))

        chunks, _ = await _pilot_chunks(CreationAgent(), stream)

        assert len(chunks) == 1
        assert UNRESOLVED in chunks[0].lower()

    @pytest.mark.asyncio
    async def test_usage_only_completion_reports_failure_and_keeps_usage(self):
        from creation_agent import CreationAgent

        async def stream(_agent, _ctx, _tools, _settings):
            yield ChatChunk(id="usage", usage=_usage())

        chunks, userdata = await _pilot_chunks(CreationAgent(), stream)

        assert len(chunks) == 1
        assert UNRESOLVED in chunks[0].lower()
        assert userdata.tokens.summary()["requests"] == 1

    @pytest.mark.asyncio
    async def test_terminal_success_releases_output_and_keeps_usage(self):
        from creation_agent import CreationAgent

        async def stream(_agent, _ctx, _tools, _settings):
            yield ChatChunk(id="answer", delta=ChoiceDelta(content="The way opens."))
            yield ChatChunk(id="usage", usage=_usage())

        chunks, userdata = await _pilot_chunks(CreationAgent(), stream)

        assert [chunk.id for chunk in chunks] == ["answer", "usage"]
        assert userdata.tokens.summary()["requests"] == 1

    @pytest.mark.asyncio
    async def test_provider_cancellation_reports_failure(self):
        from creation_agent import CreationAgent

        async def stream(_agent, _ctx, _tools, _settings):
            raise asyncio.CancelledError
            yield

        chunks, _ = await _pilot_chunks(CreationAgent(), stream)

        assert len(chunks) == 1
        assert UNRESOLVED in chunks[0].lower()

    @pytest.mark.asyncio
    async def test_player_interruption_discards_quietly(self):
        from creation_agent import CreationAgent

        async def stream(_agent, _ctx, _tools, _settings):
            yield ChatChunk(id="partial", delta=ChoiceDelta(content="The way"))
            raise asyncio.CancelledError

        chunks, _ = await _pilot_chunks(CreationAgent(), stream, interrupted=True)

        assert chunks == []

    @pytest.mark.asyncio
    async def test_complete_call_followed_by_error_never_reaches_execution(self):
        from creation_agent import CreationAgent

        executions = []

        @function_tool
        async def mutate() -> str:
            executions.append("called")
            return "mutated"

        async def stream(_agent, _ctx, _tools, _settings):
            yield ChatChunk(
                id="call",
                delta=ChoiceDelta(tool_calls=[FunctionToolCall(name="mutate", arguments="{}", call_id="call-1")]),
            )
            raise RuntimeError("provider failed after call")

        agent = CreationAgent()
        session = _pilot_session()
        with (
            patch.object(type(agent), "session", new_callable=lambda: property(lambda self: session)),
            patch("base_agent.Agent.default.llm_node", stream),
            patch("base_agent._player_interrupted", return_value=False),
        ):
            task, data = perform_llm_inference(
                node=agent.llm_node,
                chat_ctx=llm.ChatContext(),
                tool_ctx=ToolContext([mutate]),
                model_settings=ModelSettings(),
            )
            delivered = []
            async for call in data.function_ch:
                delivered.append(call)
                await mutate._func()
            await task

        assert delivered == []
        assert executions == []


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
