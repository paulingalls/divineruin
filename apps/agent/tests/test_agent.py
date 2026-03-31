"""Tests for agent.py - main DM agent and session management."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent import (
    REQUIRED_ENV_VARS,
    _extract_player_id,
    validate_env,
)
from base_agent import TTS_NUM_CHANNELS, TTS_SAMPLE_RATE, BaseGameAgent, _make_tts, _silence
from city_agent import CityAgent
from onboarding_agent import OnboardingAgent


class _TestAgent(BaseGameAgent):
    """Minimal BaseGameAgent subclass for testing voice pipeline methods."""

    def __init__(self):
        super().__init__(instructions="test", tools=[])


class TestEnvironmentValidation:
    """Test environment variable validation."""

    def test_validate_env_passes_with_all_vars_set(self):
        """validate_env should pass when all required vars are set."""
        env = {var: "test_value" for var in REQUIRED_ENV_VARS}
        with patch.dict(os.environ, env, clear=True):
            with patch("agent.VOICES", {"narrator": "voice_id", "torin": "voice_id2"}):
                validate_env()  # Should not raise

    def test_validate_env_raises_on_missing_vars(self):
        """validate_env should raise EnvironmentError if vars missing."""
        # Set all but one
        env = {var: "test_value" for var in REQUIRED_ENV_VARS[1:]}
        with patch.dict(os.environ, env, clear=True):
            with patch("agent.VOICES", {"narrator": "voice_id"}):
                with pytest.raises(EnvironmentError) as exc_info:
                    validate_env()

                assert REQUIRED_ENV_VARS[0] in str(exc_info.value)

    def test_validate_env_warns_on_empty_voices(self):
        """validate_env should warn if voice IDs are empty."""
        env = {var: "test_value" for var in REQUIRED_ENV_VARS}
        with patch.dict(os.environ, env, clear=True):
            with patch("agent.VOICES", {"narrator": "", "torin": "voice_id"}):
                with patch("agent.logger") as mock_logger:
                    validate_env()

                    mock_logger.warning.assert_called_once()
                    assert "narrator" in mock_logger.warning.call_args[0][1]


class TestTTSNode:
    """Test TTS streaming and audio generation."""

    @pytest.mark.asyncio
    async def test_tts_node_marks_latency_milestones(self):
        """tts_node should mark latency milestones."""
        agent = _TestAgent()

        async def mock_text_stream():
            yield "Hello world"

        mock_model_settings = MagicMock()

        with patch("base_agent.parse_dialogue_stream") as mock_parse:
            mock_segment = MagicMock()
            mock_segment.character = "narrator"
            mock_segment.emotion = "neutral"
            mock_segment.text = "Hello world."

            async def mock_segments():
                yield mock_segment

            mock_parse.return_value = mock_segments()

            with patch("base_agent._make_tts") as mock_make_tts:
                mock_tts = MagicMock()
                mock_stream = MagicMock()
                mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
                mock_stream.__aexit__ = AsyncMock()

                async def mock_frames():
                    yield MagicMock(frame=MagicMock())

                mock_stream.__aiter__ = lambda self: mock_frames()
                mock_tts.synthesize.return_value = mock_stream
                mock_make_tts.return_value = mock_tts

                with patch.object(agent._turn_timer, "mark") as mock_mark:
                    with patch.object(agent._turn_timer, "finish") as mock_finish:
                        frames = []
                        async for frame in agent.tts_node(mock_text_stream(), mock_model_settings):
                            frames.append(frame)

                        # Should mark tts_start at beginning
                        assert any(call[0][0] == "tts_start" for call in mock_mark.call_args_list)
                        # Should mark tts_first_byte when first frame arrives
                        assert any(call[0][0] == "tts_first_byte" for call in mock_mark.call_args_list)
                        # Should finish timer at end
                        mock_finish.assert_called_once()


class TestAudioHelpers:
    """Test audio frame generation helpers."""

    def test_silence_generates_correct_frame_length(self):
        """_silence should generate audio frame with correct sample count."""
        frame = _silence(1.0)  # 1 second

        expected_samples = TTS_SAMPLE_RATE * 1
        assert frame.sample_rate == TTS_SAMPLE_RATE
        assert frame.num_channels == TTS_NUM_CHANNELS
        assert frame.samples_per_channel == expected_samples

    def test_silence_frame_contains_zeros(self):
        """_silence should generate frame filled with zeros."""
        frame = _silence(0.5)

        # Frame data should be all zeros (silence)
        assert all(b == 0 for b in frame.data)

    def test_make_tts_creates_inworld_tts(self):
        """_make_tts should create InWorld TTS with correct parameters."""
        with patch("base_agent.inworld.TTS") as MockTTS:
            _make_tts(voice="test_voice", speaking_rate=1.2)

            MockTTS.assert_called_once_with(voice="test_voice", speaking_rate=1.2)

    def test_make_tts_omits_voice_if_empty(self):
        """_make_tts should not include voice parameter if empty."""
        with patch("base_agent.inworld.TTS") as MockTTS:
            _make_tts(voice="", speaking_rate=1.0)

            call_kwargs = MockTTS.call_args[1]
            assert "voice" not in call_kwargs
            assert call_kwargs["speaking_rate"] == 1.0


class TestSessionDataFields:
    """Test SessionData field defaults and properties."""

    def test_pre_combat_agent_type_defaults_to_none(self):
        from session_data import SessionData

        sd = SessionData(player_id="p1", location_id="loc1")
        assert sd.pre_combat_agent_type is None

    def test_pre_combat_agent_type_can_be_set(self):
        from session_data import SessionData

        sd = SessionData(player_id="p1", location_id="loc1")
        sd.pre_combat_agent_type = "wilderness"
        assert sd.pre_combat_agent_type == "wilderness"


class TestExtractPlayerId:
    """Test _extract_player_id metadata parsing and env-based fallback."""

    def _make_ctx(self, metadata: str | None = None) -> MagicMock:
        ctx = MagicMock()
        if metadata is not None:
            ctx.job.metadata = metadata
        else:
            ctx.job = None
        return ctx

    def test_valid_player_id(self):
        ctx = self._make_ctx('{"player_id": "player_abc123"}')
        assert _extract_player_id(ctx) == "player_abc123"

    def test_valid_player_id_with_hyphens(self):
        ctx = self._make_ctx('{"player_id": "player_abc-123"}')
        assert _extract_player_id(ctx) == "player_abc-123"

    def test_rejects_invalid_characters(self):
        """player_id with invalid chars falls back (dev) or raises (prod)."""
        ctx = self._make_ctx('{"player_id": "player/../etc"}')
        with patch.dict(os.environ, {"AGENT_ENV": "development"}):
            result = _extract_player_id(ctx)
            assert result == "player_1"

    def test_rejects_too_long_id(self):
        long_id = "a" * 65
        ctx = self._make_ctx(f'{{"player_id": "{long_id}"}}')
        with patch.dict(os.environ, {"AGENT_ENV": "development"}):
            result = _extract_player_id(ctx)
            assert result == "player_1"

    def test_production_raises_on_missing_metadata(self):
        ctx = self._make_ctx(None)
        with patch.dict(os.environ, {"AGENT_ENV": "production"}):
            with pytest.raises(ValueError, match="production"):
                _extract_player_id(ctx)

    def test_production_raises_on_invalid_player_id(self):
        ctx = self._make_ctx('{"player_id": "bad/id"}')
        with patch.dict(os.environ, {"AGENT_ENV": "production"}):
            with pytest.raises(ValueError, match="production"):
                _extract_player_id(ctx)

    def test_dev_fallback_with_no_metadata(self):
        ctx = self._make_ctx(None)
        with patch.dict(os.environ, {"AGENT_ENV": "development"}):
            assert _extract_player_id(ctx) == "player_1"

    def test_dev_fallback_is_default(self):
        """Without AGENT_ENV set, defaults to development (fallback allowed)."""
        ctx = self._make_ctx("{}")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AGENT_ENV", None)
            assert _extract_player_id(ctx) == "player_1"


class TestDMSession:
    """Test dm_session handler."""

    @pytest.mark.asyncio
    async def test_dm_session_creates_session_data(self):
        """dm_session should create SessionData — first session (existing player, no summary) starts at market square."""
        mock_ctx = MagicMock()
        mock_ctx.room = MagicMock()
        mock_player = {"name": "Test", "location_id": "accord_guild_hall"}

        with patch("agent.SessionData") as MockSD:
            with patch("agent.AgentSession") as MockSession:
                mock_session_instance = MagicMock()
                mock_session_instance.start = AsyncMock()
                mock_session_instance.generate_reply = AsyncMock()
                MockSession.return_value = mock_session_instance

                with patch("agent.deepgram.STT"):
                    with patch("agent.anthropic.LLM"):
                        with patch("agent._make_tts"):
                            with patch("agent.silero.VAD.load"):
                                with patch("agent.MultilingualModel"):
                                    with patch("agent.db.get_player", new_callable=AsyncMock, return_value=mock_player):
                                        with patch(
                                            "agent.db.get_last_session_summary",
                                            new_callable=AsyncMock,
                                            return_value=None,
                                        ):
                                            with patch(
                                                "agent.db.get_player_flag", new_callable=AsyncMock, return_value=False
                                            ):
                                                with patch(
                                                    "agent.db.get_location",
                                                    new_callable=AsyncMock,
                                                    return_value={"region_type": "city"},
                                                ):
                                                    from agent import dm_session

                                                    await dm_session(mock_ctx)

                MockSD.assert_called_once_with(
                    player_id="player_1",
                    location_id="accord_market_square",
                    room=mock_ctx.room,
                    patron_id="none",
                )

    @pytest.mark.asyncio
    async def test_dm_session_starts_agent_session_with_city_agent(self):
        """dm_session should start AgentSession with CityAgent for existing players."""
        mock_ctx = MagicMock()
        mock_ctx.room = MagicMock()
        mock_player = {"name": "Test", "location_id": "accord_guild_hall"}

        with patch("agent.SessionData"):
            with patch("agent.AgentSession") as MockSession:
                mock_session_instance = MagicMock()
                mock_session_instance.start = AsyncMock()
                mock_session_instance.generate_reply = AsyncMock()
                MockSession.return_value = mock_session_instance

                with patch("agent.deepgram.STT"):
                    with patch("agent.anthropic.LLM"):
                        with patch("agent._make_tts"):
                            with patch("agent.silero.VAD.load"):
                                with patch("agent.MultilingualModel"):
                                    with patch("agent.db.get_player", new_callable=AsyncMock, return_value=mock_player):
                                        with patch(
                                            "agent.db.get_last_session_summary",
                                            new_callable=AsyncMock,
                                            return_value=None,
                                        ):
                                            with patch(
                                                "agent.db.get_player_flag", new_callable=AsyncMock, return_value=False
                                            ):
                                                with patch(
                                                    "agent.db.get_location",
                                                    new_callable=AsyncMock,
                                                    return_value={"region_type": "city"},
                                                ):
                                                    from agent import dm_session

                                                    await dm_session(mock_ctx)

                mock_session_instance.start.assert_awaited_once()
                start_call = mock_session_instance.start.call_args
                assert start_call[1]["room"] == mock_ctx.room
                assert isinstance(start_call[1]["agent"], CityAgent)

    @pytest.mark.asyncio
    async def test_dm_session_generates_initial_greeting(self):
        """dm_session should generate initial greeting with enter_location call."""
        mock_ctx = MagicMock()
        mock_ctx.room = MagicMock()
        mock_player = {"name": "Test", "location_id": "accord_guild_hall"}

        with patch("agent.SessionData"):
            with patch("agent.AgentSession") as MockSession:
                mock_session_instance = MagicMock()
                mock_session_instance.start = AsyncMock()
                mock_session_instance.generate_reply = AsyncMock()
                MockSession.return_value = mock_session_instance

                with patch("agent.deepgram.STT"):
                    with patch("agent.anthropic.LLM"):
                        with patch("agent._make_tts"):
                            with patch("agent.silero.VAD.load"):
                                with patch("agent.MultilingualModel"):
                                    with patch("agent.db.get_player", new_callable=AsyncMock, return_value=mock_player):
                                        with patch(
                                            "agent.db.get_last_session_summary",
                                            new_callable=AsyncMock,
                                            return_value=None,
                                        ):
                                            with patch(
                                                "agent.db.get_player_flag", new_callable=AsyncMock, return_value=False
                                            ):
                                                with patch(
                                                    "agent.db.get_location",
                                                    new_callable=AsyncMock,
                                                    return_value={"region_type": "city"},
                                                ):
                                                    from agent import dm_session

                                                    await dm_session(mock_ctx)

                mock_session_instance.generate_reply.assert_awaited_once()
                call_kwargs = mock_session_instance.generate_reply.call_args[1]
                instructions = call_kwargs["instructions"]
                assert "enter_location" in instructions
                assert "market" in instructions.lower()

    @pytest.mark.asyncio
    async def test_dm_session_dispatches_onboarding_agent_for_mid_onboarding_player(self):
        """Player with onboarding_beat flag should get OnboardingAgent, not CityAgent."""
        mock_ctx = MagicMock()
        mock_ctx.room = MagicMock()
        mock_player = {
            "name": "Aric",
            "location_id": "accord_market_square",
            "flags": {"onboarding_beat": 3, "companion_met": True},
        }

        with patch("agent.SessionData"):
            with patch("agent.AgentSession") as MockSession:
                mock_session_instance = MagicMock()
                mock_session_instance.start = AsyncMock()
                mock_session_instance.generate_reply = AsyncMock()
                MockSession.return_value = mock_session_instance

                with patch("agent.deepgram.STT"):
                    with patch("agent.anthropic.LLM"):
                        with patch("agent._make_tts"):
                            with patch("agent.silero.VAD.load"):
                                with patch("agent.MultilingualModel"):
                                    with patch("agent.db.get_player", new_callable=AsyncMock, return_value=mock_player):
                                        with patch(
                                            "agent.db.get_last_session_summary",
                                            new_callable=AsyncMock,
                                            return_value=None,
                                        ):
                                            from agent import dm_session

                                            await dm_session(mock_ctx)

                mock_session_instance.start.assert_awaited_once()
                start_call = mock_session_instance.start.call_args
                assert isinstance(start_call[1]["agent"], OnboardingAgent)

    @pytest.mark.asyncio
    async def test_dm_session_dispatches_city_agent_for_completed_onboarding(self):
        """Player with onboarding_beat='complete' should get CityAgent."""
        mock_ctx = MagicMock()
        mock_ctx.room = MagicMock()
        mock_player = {
            "name": "Aric",
            "location_id": "accord_guild_hall",
            "flags": {"onboarding_beat": "complete", "companion_met": True},
        }

        with patch("agent.SessionData"):
            with patch("agent.AgentSession") as MockSession:
                mock_session_instance = MagicMock()
                mock_session_instance.start = AsyncMock()
                mock_session_instance.generate_reply = AsyncMock()
                MockSession.return_value = mock_session_instance

                with patch("agent.deepgram.STT"):
                    with patch("agent.anthropic.LLM"):
                        with patch("agent._make_tts"):
                            with patch("agent.silero.VAD.load"):
                                with patch("agent.MultilingualModel"):
                                    with patch("agent.db.get_player", new_callable=AsyncMock, return_value=mock_player):
                                        with patch(
                                            "agent.db.get_last_session_summary",
                                            new_callable=AsyncMock,
                                            return_value=None,
                                        ):
                                            with patch(
                                                "agent.db.get_location",
                                                new_callable=AsyncMock,
                                                return_value={"region_type": "city"},
                                            ):
                                                from agent import dm_session

                                                await dm_session(mock_ctx)

                mock_session_instance.start.assert_awaited_once()
                start_call = mock_session_instance.start.call_args
                assert isinstance(start_call[1]["agent"], CityAgent)
