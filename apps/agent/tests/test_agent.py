"""Tests for agent.py - main DM agent and session management."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent import (
    REQUIRED_ENV_VARS,
    START_LOCATION,
    TTS_NUM_CHANNELS,
    TTS_SAMPLE_RATE,
    DungeonMasterAgent,
    _extract_player_id,
    _make_tts,
    _silence,
    validate_env,
)


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


class TestDungeonMasterAgent:
    """Test DungeonMasterAgent initialization and lifecycle."""

    def test_init_sets_instructions_and_tools(self):
        """__init__ should set initial instructions and tools."""
        with patch("agent.build_system_prompt") as mock_build_prompt:
            mock_build_prompt.return_value = "System prompt"

            agent = DungeonMasterAgent()

            mock_build_prompt.assert_called_once_with(START_LOCATION)
            assert agent.instructions == "System prompt"
            assert len(agent.tools) > 0

    def test_init_creates_turn_timer(self):
        """__init__ should create a TurnTimer instance."""
        with patch("agent.build_system_prompt", return_value="prompt"):
            agent = DungeonMasterAgent()

            assert agent._turn_timer is not None

    def test_init_sets_background_to_none(self):
        """__init__ should initialize background process to None."""
        with patch("agent.build_system_prompt", return_value="prompt"):
            agent = DungeonMasterAgent()

            assert agent._background is None

    @pytest.mark.asyncio
    async def test_on_enter_starts_background_process(self):
        """on_enter should start background process."""
        with patch("agent.build_system_prompt", return_value="prompt"):
            agent = DungeonMasterAgent()

        mock_session = MagicMock()
        mock_session_data = MagicMock()
        mock_session.userdata = mock_session_data

        with patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)):
            with patch("agent.BackgroundProcess") as MockBP:
                mock_bp_instance = MagicMock()
                MockBP.return_value = mock_bp_instance

                await agent.on_enter()

                MockBP.assert_called_once_with(
                    agent=agent,
                    session=mock_session,
                    session_data=mock_session_data,
                )
                mock_bp_instance.start.assert_called_once()
                assert agent._background is mock_bp_instance

    @pytest.mark.asyncio
    async def test_on_user_turn_completed_starts_timer(self):
        """on_user_turn_completed should start turn timer."""
        with patch("agent.build_system_prompt", return_value="prompt"):
            agent = DungeonMasterAgent()

        mock_turn_ctx = MagicMock()
        mock_message = MagicMock()
        mock_session_data = MagicMock()
        mock_session_data.last_player_speech_time = 0

        mock_session = MagicMock()
        mock_session.userdata = mock_session_data

        with patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)):
            with patch.object(agent._turn_timer, "start") as mock_start:
                with patch.object(agent._turn_timer, "mark") as mock_mark:
                    with patch.object(agent, "_build_hot_context", return_value=""):
                        await agent.on_user_turn_completed(mock_turn_ctx, mock_message)

                        mock_start.assert_called_once()
                        mock_mark.assert_called_once_with("user_turn_end")

    @pytest.mark.asyncio
    async def test_on_user_turn_completed_updates_player_speech_time(self):
        """on_user_turn_completed should update last_player_speech_time."""
        with patch("agent.build_system_prompt", return_value="prompt"):
            agent = DungeonMasterAgent()

        mock_turn_ctx = MagicMock()
        mock_message = MagicMock()
        mock_session_data = MagicMock()
        mock_session_data.last_player_speech_time = 0

        mock_session = MagicMock()
        mock_session.userdata = mock_session_data

        with patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)):
            with patch.object(agent, "_build_hot_context", return_value=""):
                before = mock_session_data.last_player_speech_time
                await agent.on_user_turn_completed(mock_turn_ctx, mock_message)

                assert mock_session_data.last_player_speech_time > before

    @pytest.mark.asyncio
    async def test_on_user_turn_completed_adds_hot_context_to_turn(self):
        """on_user_turn_completed should add hot context to chat."""
        with patch("agent.build_system_prompt", return_value="prompt"):
            agent = DungeonMasterAgent()

        mock_turn_ctx = MagicMock()
        mock_message = MagicMock()
        mock_session_data = MagicMock()

        mock_session = MagicMock()
        mock_session.userdata = mock_session_data

        with patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)):
            with patch.object(agent, "_build_hot_context", return_value="[Context: Tavern]"):
                await agent.on_user_turn_completed(mock_turn_ctx, mock_message)

                mock_turn_ctx.add_message.assert_called_once_with(role="assistant", content="[Context: Tavern]")

    @pytest.mark.asyncio
    async def test_on_user_turn_completed_skips_empty_hot_context(self):
        """on_user_turn_completed should not add message if hot context is empty."""
        with patch("agent.build_system_prompt", return_value="prompt"):
            agent = DungeonMasterAgent()

        mock_turn_ctx = MagicMock()
        mock_message = MagicMock()
        mock_session_data = MagicMock()

        mock_session = MagicMock()
        mock_session.userdata = mock_session_data

        with patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)):
            with patch.object(agent, "_build_hot_context", return_value=""):
                await agent.on_user_turn_completed(mock_turn_ctx, mock_message)

                mock_turn_ctx.add_message.assert_not_called()


class TestHotContextBuilding:
    """Test _build_hot_context per-turn context assembly (pure in-memory, no DB)."""

    def test_build_hot_context_includes_location_and_time(self):
        """_build_hot_context should include location name and world time."""
        with patch("agent.build_system_prompt", return_value="prompt"):
            agent = DungeonMasterAgent()

        mock_sd = MagicMock()
        mock_sd.location_id = "tavern"
        mock_sd.world_time = "evening"
        mock_sd.cached_location_name = "The Rusty Sword"
        mock_sd.cached_quest_summaries = []
        mock_sd.cached_npc_names = []
        mock_sd.recent_events = []
        mock_sd.combat_state = None

        result = agent._build_hot_context(mock_sd)

        assert "[Context: The Rusty Sword, evening]" in result

    def test_build_hot_context_uses_location_id_if_no_name(self):
        """_build_hot_context should fall back to location_id if cached name is empty."""
        with patch("agent.build_system_prompt", return_value="prompt"):
            agent = DungeonMasterAgent()

        mock_sd = MagicMock()
        mock_sd.location_id = "unknown_place"
        mock_sd.world_time = "morning"
        mock_sd.cached_location_name = ""
        mock_sd.cached_quest_summaries = []
        mock_sd.cached_npc_names = []
        mock_sd.recent_events = []
        mock_sd.combat_state = None

        result = agent._build_hot_context(mock_sd)

        assert "[Context: unknown_place, morning]" in result

    def test_build_hot_context_includes_active_quest_objectives(self):
        """_build_hot_context should include cached quest summaries."""
        with patch("agent.build_system_prompt", return_value="prompt"):
            agent = DungeonMasterAgent()

        mock_sd = MagicMock()
        mock_sd.location_id = "forest"
        mock_sd.world_time = "day"
        mock_sd.cached_location_name = "Dark Forest"
        mock_sd.cached_quest_summaries = ["Find the Artifact: Search the ruins"]
        mock_sd.cached_npc_names = []
        mock_sd.recent_events = []
        mock_sd.combat_state = None

        result = agent._build_hot_context(mock_sd)

        assert "[Quests:" in result
        assert "Find the Artifact" in result
        assert "Search the ruins" in result

    def test_build_hot_context_includes_recent_events(self):
        """_build_hot_context should include recent events from session data."""
        with patch("agent.build_system_prompt", return_value="prompt"):
            agent = DungeonMasterAgent()

        mock_sd = MagicMock()
        mock_sd.location_id = "town"
        mock_sd.world_time = "night"
        mock_sd.cached_location_name = "Town Square"
        mock_sd.cached_quest_summaries = []
        mock_sd.cached_npc_names = []
        mock_sd.recent_events = ["Found a key", "Defeated goblin", "Talked to merchant", "Entered tavern"]
        mock_sd.combat_state = None

        result = agent._build_hot_context(mock_sd)

        assert "[Recent:" in result
        # Should only include last 3 events
        assert "Talked to merchant" in result
        assert "Entered tavern" in result
        assert "Found a key" not in result  # Too old

    def test_build_hot_context_includes_npcs_nearby(self):
        """_build_hot_context should include cached NPC names."""
        with patch("agent.build_system_prompt", return_value="prompt"):
            agent = DungeonMasterAgent()

        mock_sd = MagicMock()
        mock_sd.location_id = "guild_hall"
        mock_sd.world_time = "evening"
        mock_sd.cached_location_name = "Guild Hall"
        mock_sd.cached_quest_summaries = []
        mock_sd.cached_npc_names = ["Guildmaster Torin", "Elara the Sage"]
        mock_sd.recent_events = []
        mock_sd.combat_state = None

        result = agent._build_hot_context(mock_sd)

        assert "[NPCs nearby:" in result
        assert "Guildmaster Torin" in result
        assert "Elara the Sage" in result

    def test_build_hot_context_handles_npc_without_name(self):
        """_build_hot_context should use whatever name is cached (fallback handled at cache time)."""
        with patch("agent.build_system_prompt", return_value="prompt"):
            agent = DungeonMasterAgent()

        mock_sd = MagicMock()
        mock_sd.location_id = "cave"
        mock_sd.world_time = "day"
        mock_sd.cached_location_name = "Cave"
        mock_sd.cached_quest_summaries = []
        mock_sd.cached_npc_names = ["mysterious_figure"]
        mock_sd.recent_events = []
        mock_sd.combat_state = None

        result = agent._build_hot_context(mock_sd)

        assert "mysterious_figure" in result


class TestTTSNode:
    """Test TTS streaming and audio generation."""

    @pytest.mark.asyncio
    async def test_tts_node_marks_latency_milestones(self):
        """tts_node should mark latency milestones."""
        with patch("agent.build_system_prompt", return_value="prompt"):
            agent = DungeonMasterAgent()

        async def mock_text_stream():
            yield "Hello world"

        mock_model_settings = MagicMock()

        with patch("agent.parse_dialogue_stream") as mock_parse:
            mock_segment = MagicMock()
            mock_segment.character = "narrator"
            mock_segment.emotion = "neutral"
            mock_segment.text = "Hello world."

            async def mock_segments():
                yield mock_segment

            mock_parse.return_value = mock_segments()

            with patch("agent._make_tts") as mock_make_tts:
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
        with patch("agent.inworld.TTS") as MockTTS:
            _make_tts(voice="test_voice", speaking_rate=1.2)

            MockTTS.assert_called_once_with(voice="test_voice", speaking_rate=1.2)

    def test_make_tts_omits_voice_if_empty(self):
        """_make_tts should not include voice parameter if empty."""
        with patch("agent.inworld.TTS") as MockTTS:
            _make_tts(voice="", speaking_rate=1.0)

            call_kwargs = MockTTS.call_args[1]
            assert "voice" not in call_kwargs
            assert call_kwargs["speaking_rate"] == 1.0


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
                                                from agent import dm_session

                                                await dm_session(mock_ctx)

                MockSD.assert_called_once_with(
                    player_id="player_1",
                    location_id="accord_market_square",
                    room=mock_ctx.room,
                    patron_id="none",
                )

    @pytest.mark.asyncio
    async def test_dm_session_starts_agent_session(self):
        """dm_session should start AgentSession with DM agent."""
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
                                                from agent import dm_session

                                                await dm_session(mock_ctx)

                mock_session_instance.start.assert_awaited_once()
                start_call = mock_session_instance.start.call_args
                assert start_call[1]["room"] == mock_ctx.room
                assert isinstance(start_call[1]["agent"], DungeonMasterAgent)

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
                                                from agent import dm_session

                                                await dm_session(mock_ctx)

                mock_session_instance.generate_reply.assert_awaited_once()
                call_kwargs = mock_session_instance.generate_reply.call_args[1]
                instructions = call_kwargs["instructions"]
                assert "enter_location" in instructions
                assert "market" in instructions.lower()
