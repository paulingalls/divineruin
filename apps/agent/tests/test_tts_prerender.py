"""Tests for TTS pre-rendering module."""

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tts_prerender import synthesize_to_file


def _make_mock_frame(data: bytes) -> MagicMock:
    frame = MagicMock()
    frame.data = data
    return frame


def _make_mock_event(frame: MagicMock) -> MagicMock:
    event = MagicMock()
    event.frame = frame
    return event


class TestSynthesizeToFile:
    @pytest.mark.asyncio
    async def test_writes_mp3_file(self):
        """Verify an MP3 file is written."""
        mp3_data = b"\xff\xfb\x90\x00" * 1000  # fake MP3 frames
        mock_frame = _make_mock_frame(mp3_data)
        mock_event = _make_mock_event(mock_frame)

        mock_stream = MagicMock()
        mock_stream.__aiter__ = lambda self: self
        mock_stream.__anext__ = AsyncMock(side_effect=[mock_event, StopAsyncIteration()])
        mock_stream.aclose = AsyncMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_audio.mp3")

            with patch("tts_prerender.TTS") as MockTTS:
                mock_tts_instance = MockTTS.return_value
                mock_tts_instance.synthesize.return_value = mock_stream

                filename = await synthesize_to_file("Hello world", "voice_1", output_path)

            assert filename == "test_audio.mp3"
            assert os.path.exists(output_path)
            assert os.path.getsize(output_path) == len(mp3_data)

            # Verify raw bytes match
            with open(output_path, "rb") as f:
                assert f.read() == mp3_data

    @pytest.mark.asyncio
    async def test_passes_voice_and_encoding_to_tts(self):
        """Verify TTS is constructed with voice_id and MP3 encoding."""
        mock_frame = _make_mock_frame(b"\x00" * 10)
        mock_event = _make_mock_event(mock_frame)

        mock_stream = MagicMock()
        mock_stream.__aiter__ = lambda self: self
        mock_stream.__anext__ = AsyncMock(side_effect=[mock_event, StopAsyncIteration()])
        mock_stream.aclose = AsyncMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test.mp3")

            with patch("tts_prerender.TTS") as MockTTS:
                mock_tts_instance = MockTTS.return_value
                mock_tts_instance.synthesize.return_value = mock_stream

                await synthesize_to_file("Test", "MY_VOICE_ID", output_path)

            MockTTS.assert_called_once_with(voice="MY_VOICE_ID", encoding="MP3")

    @pytest.mark.asyncio
    async def test_creates_parent_directory(self):
        """Verify parent directory is created if it doesn't exist."""
        mock_frame = _make_mock_frame(b"\x00" * 100)
        mock_event = _make_mock_event(mock_frame)

        mock_stream = MagicMock()
        mock_stream.__aiter__ = lambda self: self
        mock_stream.__anext__ = AsyncMock(side_effect=[mock_event, StopAsyncIteration()])
        mock_stream.aclose = AsyncMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            nested_path = os.path.join(tmpdir, "subdir", "deep", "test.mp3")

            with patch("tts_prerender.TTS") as MockTTS:
                mock_tts_instance = MockTTS.return_value
                mock_tts_instance.synthesize.return_value = mock_stream

                await synthesize_to_file("Test", "voice_1", nested_path)

            assert os.path.exists(nested_path)

    @pytest.mark.asyncio
    async def test_handles_multiple_frames(self):
        """Verify multiple frames are concatenated."""
        frame1 = _make_mock_frame(b"\x01" * 100)
        frame2 = _make_mock_frame(b"\x02" * 100)
        event1 = _make_mock_event(frame1)
        event2 = _make_mock_event(frame2)

        mock_stream = MagicMock()
        mock_stream.__aiter__ = lambda self: self
        mock_stream.__anext__ = AsyncMock(side_effect=[event1, event2, StopAsyncIteration()])
        mock_stream.aclose = AsyncMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "multi.mp3")

            with patch("tts_prerender.TTS") as MockTTS:
                mock_tts_instance = MockTTS.return_value
                mock_tts_instance.synthesize.return_value = mock_stream

                await synthesize_to_file("Two frames", "voice_1", output_path)

            assert os.path.getsize(output_path) == 200

    @pytest.mark.asyncio
    async def test_rejects_relative_path_traversal(self):
        """Reject paths containing '..' to prevent directory traversal."""
        with pytest.raises(ValueError, match="Path traversal"):
            await synthesize_to_file("Hello", "voice_1", "/tmp/audio/../../../etc/passwd")

    @pytest.mark.asyncio
    async def test_rejects_absolute_path_traversal(self):
        """Reject paths with '..' even in nested components."""
        with pytest.raises(ValueError, match="Path traversal"):
            await synthesize_to_file("Hello", "voice_1", "output/../../secret.mp3")

    @pytest.mark.asyncio
    async def test_returns_filename_only(self):
        """Verify returned value is just the filename, not full path."""
        mock_frame = _make_mock_frame(b"\x00" * 10)
        mock_event = _make_mock_event(mock_frame)

        mock_stream = MagicMock()
        mock_stream.__aiter__ = lambda self: self
        mock_stream.__anext__ = AsyncMock(side_effect=[mock_event, StopAsyncIteration()])
        mock_stream.aclose = AsyncMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "activity_abc123.mp3")

            with patch("tts_prerender.TTS") as MockTTS:
                mock_tts_instance = MockTTS.return_value
                mock_tts_instance.synthesize.return_value = mock_stream

                result = await synthesize_to_file("Test", "voice_1", output_path)

            assert result == "activity_abc123.mp3"
            assert "/" not in result
