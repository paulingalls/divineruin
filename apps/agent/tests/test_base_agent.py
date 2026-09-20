"""Tests for BaseGameAgent — shared voice pipeline and lifecycle infrastructure."""

import asyncio
import importlib
import inspect
import logging
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents import Agent

import base_agent
from base_agent import TTS_NUM_CHANNELS, TTS_SAMPLE_RATE, BaseGameAgent, _silence
from session_data import SessionData


def _concrete_agent_types() -> tuple[type[Agent], ...]:
    agent_dir = pathlib.Path(base_agent.__file__).parent
    found: list[type[Agent]] = []
    for path in sorted(agent_dir.glob("*.py")):
        if path.name == "base_agent.py":
            continue
        module = importlib.import_module(path.stem)
        found.extend(
            member
            for _, member in inspect.getmembers(module, inspect.isclass)
            if member.__module__ == module.__name__ and issubclass(member, Agent)
        )
    return tuple(found)


CONCRETE_AGENT_TYPES = _concrete_agent_types()


def _application_errors(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record for record in caplog.records if record.levelno == logging.ERROR and record.name.startswith("divineruin.")
    ]


def test_agent_walk_finds_every_current_concrete_agent():
    assert len(CONCRETE_AGENT_TYPES) >= 7


@pytest.mark.parametrize("agent_type", CONCRETE_AGENT_TYPES, ids=lambda agent_type: agent_type.__name__)
@pytest.mark.asyncio
async def test_every_concrete_agent_reports_its_entry_failure_once(agent_type, caplog):
    agent = agent_type()
    failure = RuntimeError(f"{agent_type.__module__} entry exploded")
    if hasattr(agent, "_affect_analyzer"):
        agent._affect_analyzer.start = MagicMock()

    with (
        patch.object(
            type(agent), "session", new_callable=lambda: property(lambda self: (_ for _ in ()).throw(failure))
        ),
        caplog.at_level(logging.ERROR),
    ):
        task = asyncio.create_task(agent.on_enter())
        done, pending = await asyncio.wait({task}, timeout=5)

    assert done == {task}
    assert pending == set()
    assert task.exception() is None
    [record] = _application_errors(caplog)
    assert agent_type.__name__.lower() in record.getMessage().replace("_", "").lower()
    assert record.exc_info is not None
    assert record.exc_info[1] is failure
    assert "entry exploded" in logging.Formatter().format(record)


class TestBaseGameAgentInit:
    """Test BaseGameAgent initialization."""

    def test_init_sets_instructions_and_tools(self):
        """__init__ should set instructions and tools on the Agent."""
        agent = BaseGameAgent(instructions="Test prompt", tools=[])

        assert agent.instructions == "Test prompt"
        assert agent.tools == []

    def test_init_creates_turn_timer(self):
        """__init__ should create a TurnTimer instance."""
        agent = BaseGameAgent(instructions="prompt")
        assert agent._turn_timer is not None

    def test_init_creates_affect_analyzer(self):
        """__init__ should create a PlayerAffectAnalyzer instance."""
        agent = BaseGameAgent(instructions="prompt")
        assert agent._affect_analyzer is not None

    def test_init_sets_transcript_to_none(self):
        """__init__ should initialize transcript logger to None."""
        agent = BaseGameAgent(instructions="prompt")
        assert agent._transcript is None

    def test_init_sets_empty_bg_tasks(self):
        """__init__ should initialize empty background task set."""
        agent = BaseGameAgent(instructions="prompt")
        assert agent._bg_tasks == set()

    def test_init_accepts_chat_ctx(self):
        """__init__ should accept chat_ctx and pass it to Agent base class."""
        from livekit.agents.llm import ChatContext

        ctx = ChatContext()
        ctx.add_message(role="user", content="test message")
        agent = BaseGameAgent(instructions="prompt", chat_ctx=ctx)
        # LiveKit wraps chat_ctx; verify the message was carried through
        assert len(agent.chat_ctx.items) > 0


class TestBaseGameAgentLifecycle:
    """Test BaseGameAgent on_enter / on_exit lifecycle."""

    @pytest.mark.asyncio
    async def test_on_enter_starts_affect_analyzer(self):
        """on_enter should start the affect analyzer."""
        agent = BaseGameAgent(instructions="prompt")
        mock_session = MagicMock()
        mock_sd = MagicMock()
        mock_sd.room = MagicMock()
        mock_sd.event_bus = MagicMock()
        mock_session.userdata = mock_sd

        with patch.object(agent, "_affect_analyzer") as mock_analyzer:
            with patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)):
                with patch("base_agent.TranscriptLogger"):
                    await agent.on_enter()

            mock_analyzer.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_enter_creates_transcript_logger(self):
        """on_enter should initialize the transcript logger."""
        agent = BaseGameAgent(instructions="prompt")
        room = MagicMock()
        sd = SessionData(player_id="p", location_id="", room=room)
        mock_session = MagicMock()
        mock_session.userdata = sd

        with patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)):
            with patch("base_agent.TranscriptLogger") as MockTL:
                MockTL.return_value = MagicMock()
                await agent.on_enter()

                MockTL.assert_called_once_with(room, sd.event_bus, log_path=None)
                assert agent._transcript is not None

    @pytest.mark.asyncio
    async def test_every_agent_in_a_session_appends_to_one_transcript(self, tmp_path):
        """The transcript is SESSION-scoped, so the end-of-session recap reads the whole
        conversation. TranscriptLogger mints a fresh timestamped path per instance when given
        none, so per-agent handles left the recap holding only the last agent's half — the
        post-fight agent's, after every combat handoff.

        _default_log_path is stubbed to hand out DISTINCT paths. The real one is second-
        granular, so two agents entering in the same second collide on one filename and this
        guard passes without the seam existing at all (constraint 1).
        """
        sd = SessionData(player_id="p", location_id="", room=None)
        mock_session = MagicMock()
        mock_session.userdata = sd
        minted = iter([str(tmp_path / "first.log"), str(tmp_path / "second.log")])

        first, second = BaseGameAgent(instructions="a"), BaseGameAgent(instructions="b")
        with (
            patch.object(BaseGameAgent, "session", new_callable=lambda: property(lambda self: mock_session)),
            patch("transcript._default_log_path", side_effect=lambda: next(minted)),
        ):
            await first.on_enter()
            await first.on_exit()  # the handoff
            await second.on_enter()

        assert first._transcript is not None and second._transcript is not None
        assert second._transcript.log_path == first._transcript.log_path == sd.transcript_path

    @pytest.mark.asyncio
    async def test_on_exit_cancels_bg_tasks(self):
        """on_exit should cancel all in-flight background tasks."""
        agent = BaseGameAgent(instructions="prompt")
        mock_session = MagicMock()
        mock_session.userdata = MagicMock()

        mock_task = MagicMock()
        mock_task.cancelled.return_value = False
        mock_task.exception.return_value = None
        agent._bg_tasks.add(mock_task)

        with patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)):
            with patch("asyncio.gather", new_callable=AsyncMock):
                await agent.on_exit()

        mock_task.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_exit_stops_affect_analyzer(self):
        """on_exit should stop the affect analyzer."""
        agent = BaseGameAgent(instructions="prompt")
        mock_session = MagicMock()
        mock_session.userdata = MagicMock()
        agent._affect_analyzer = MagicMock()
        agent._affect_analyzer.stop = AsyncMock()

        with patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)):
            await agent.on_exit()

        agent._affect_analyzer.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_exit_closes_transcript(self):
        """on_exit should close the transcript logger if present."""
        agent = BaseGameAgent(instructions="prompt")
        mock_session = MagicMock()
        mock_session.userdata = MagicMock()
        agent._affect_analyzer = MagicMock()
        agent._affect_analyzer.stop = AsyncMock()
        agent._transcript = MagicMock()

        with patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)):
            await agent.on_exit()

        agent._transcript.close.assert_called_once()


class TestBaseGameAgentInfrastructure:
    """Test shared infrastructure methods."""

    def test_fire_and_forget_creates_task(self):
        """_fire_and_forget should create an asyncio task and track it."""
        agent = BaseGameAgent(instructions="prompt")

        with patch("asyncio.create_task") as mock_create:
            mock_task = MagicMock()
            mock_create.return_value = mock_task
            coro = AsyncMock()()

            agent._fire_and_forget(coro)

            mock_create.assert_called_once()
            assert mock_task in agent._bg_tasks
            mock_task.add_done_callback.assert_called_once()

        coro.close()


class TestHelperFunctions:
    """Test module-level helper functions."""

    def test_silence_returns_audio_frame(self):
        """_silence should return an AudioFrame with correct duration."""
        frame = _silence(0.5)

        expected_samples = int(TTS_SAMPLE_RATE * 0.5)
        assert frame.sample_rate == TTS_SAMPLE_RATE
        assert frame.num_channels == TTS_NUM_CHANNELS
        assert frame.samples_per_channel == expected_samples


class TestAgentModuleImports:
    """Test that agent.py still imports _make_tts for session creation."""

    def test_agent_module_imports_make_tts(self):
        """agent module should import _make_tts from base_agent (used in dm_session)."""
        from agent import _make_tts as agent_make_tts
        from base_agent import _make_tts as base_make_tts

        assert agent_make_tts is base_make_tts
