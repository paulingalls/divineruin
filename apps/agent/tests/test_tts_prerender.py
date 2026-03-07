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
    async def test_writes_wav_file(self):
        """Verify a WAV file is written with correct format."""
        # Create mock PCM data (1 second of silence at 24kHz, 16-bit mono)
        pcm_data = b"\x00\x00" * 24000
        mock_frame = _make_mock_frame(pcm_data)
        mock_event = _make_mock_event(mock_frame)

        mock_stream = MagicMock()
        mock_stream.__aiter__ = lambda self: self
        mock_stream.__anext__ = AsyncMock(side_effect=[mock_event, StopAsyncIteration()])
        mock_stream.aclose = AsyncMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_audio.wav")

            with patch("tts_prerender.TTS") as MockTTS:
                mock_tts_instance = MockTTS.return_value
                mock_tts_instance.synthesize.return_value = mock_stream

                filename = await synthesize_to_file("Hello world", "voice_1", output_path)

            assert filename == "test_audio.wav"
            assert os.path.exists(output_path)
            assert os.path.getsize(output_path) > 0

            # Verify it's a valid WAV file
            import wave

            with wave.open(output_path, "rb") as wf:
                assert wf.getnchannels() == 1
                assert wf.getsampwidth() == 2
                assert wf.getframerate() == 24000
                assert wf.getnframes() == 24000

    @pytest.mark.asyncio
    async def test_creates_parent_directory(self):
        """Verify parent directory is created if it doesn't exist."""
        pcm_data = b"\x00\x00" * 100
        mock_frame = _make_mock_frame(pcm_data)
        mock_event = _make_mock_event(mock_frame)

        mock_stream = MagicMock()
        mock_stream.__aiter__ = lambda self: self
        mock_stream.__anext__ = AsyncMock(side_effect=[mock_event, StopAsyncIteration()])
        mock_stream.aclose = AsyncMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            nested_path = os.path.join(tmpdir, "subdir", "deep", "test.wav")

            with patch("tts_prerender.TTS") as MockTTS:
                mock_tts_instance = MockTTS.return_value
                mock_tts_instance.synthesize.return_value = mock_stream

                await synthesize_to_file("Test", "voice_1", nested_path)

            assert os.path.exists(nested_path)

    @pytest.mark.asyncio
    async def test_handles_multiple_frames(self):
        """Verify multiple PCM frames are concatenated."""
        frame1 = _make_mock_frame(b"\x01\x00" * 100)
        frame2 = _make_mock_frame(b"\x02\x00" * 100)
        event1 = _make_mock_event(frame1)
        event2 = _make_mock_event(frame2)

        mock_stream = MagicMock()
        mock_stream.__aiter__ = lambda self: self
        mock_stream.__anext__ = AsyncMock(side_effect=[event1, event2, StopAsyncIteration()])
        mock_stream.aclose = AsyncMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "multi.wav")

            with patch("tts_prerender.TTS") as MockTTS:
                mock_tts_instance = MockTTS.return_value
                mock_tts_instance.synthesize.return_value = mock_stream

                await synthesize_to_file("Two frames", "voice_1", output_path)

            import wave

            with wave.open(output_path, "rb") as wf:
                # 200 samples total (100 + 100)
                assert wf.getnframes() == 200

    @pytest.mark.asyncio
    async def test_returns_filename_only(self):
        """Verify returned value is just the filename, not full path."""
        mock_frame = _make_mock_frame(b"\x00\x00" * 10)
        mock_event = _make_mock_event(mock_frame)

        mock_stream = MagicMock()
        mock_stream.__aiter__ = lambda self: self
        mock_stream.__anext__ = AsyncMock(side_effect=[mock_event, StopAsyncIteration()])
        mock_stream.aclose = AsyncMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "activity_abc123.wav")

            with patch("tts_prerender.TTS") as MockTTS:
                mock_tts_instance = MockTTS.return_value
                mock_tts_instance.synthesize.return_value = mock_stream

                result = await synthesize_to_file("Test", "voice_1", output_path)

            assert result == "activity_abc123.wav"
            assert "/" not in result
