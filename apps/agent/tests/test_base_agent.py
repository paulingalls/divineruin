"""Tests for BaseGameAgent — shared voice pipeline and lifecycle infrastructure."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from base_agent import TTS_NUM_CHANNELS, TTS_SAMPLE_RATE, BaseGameAgent, _make_tts, _silence


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
        mock_session = MagicMock()
        mock_sd = MagicMock()
        mock_sd.room = "test_room"
        mock_sd.event_bus = MagicMock()
        mock_session.userdata = mock_sd

        with patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)):
            with patch("base_agent.TranscriptLogger") as MockTL:
                MockTL.return_value = MagicMock()
                await agent.on_enter()

                MockTL.assert_called_once_with("test_room", mock_sd.event_bus)
                assert agent._transcript is not None

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

    def test_make_tts_returns_inworld_tts(self):
        """_make_tts should return an Inworld TTS instance."""
        with patch("base_agent.inworld") as mock_inworld:
            mock_inworld.TTS.return_value = MagicMock()
            _make_tts(voice="test_voice", speaking_rate=1.2)

            mock_inworld.TTS.assert_called_once_with(voice="test_voice", speaking_rate=1.2)

    def test_make_tts_omits_voice_when_empty(self):
        """_make_tts should not pass voice kwarg when empty string."""
        with patch("base_agent.inworld") as mock_inworld:
            mock_inworld.TTS.return_value = MagicMock()
            _make_tts(voice="", speaking_rate=1.0)

            mock_inworld.TTS.assert_called_once_with(speaking_rate=1.0)


class TestAgentModuleImports:
    """Test that agent.py still imports _make_tts for session creation."""

    def test_agent_module_imports_make_tts(self):
        """agent module should import _make_tts from base_agent (used in dm_session)."""
        from agent import _make_tts as agent_make_tts
        from base_agent import _make_tts as base_make_tts

        assert agent_make_tts is base_make_tts
