"""Tests for TTS pre-rendering module."""

import os
import tempfile

import pytest

from tts_prerender import synthesize_to_file


def _fake_synthesize(data: bytes):
    """Return a synthesize function that yields fixed data."""

    async def _synth(text: str, voice_id: str) -> bytes:
        return data

    return _synth


class TestSynthesizeToFile:
    async def test_writes_mp3_file(self):
        mp3_data = b"\xff\xfb\x90\x00" * 1000
        synth = _fake_synthesize(mp3_data)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_audio.mp3")
            filename = await synthesize_to_file("Hello world", "voice_1", output_path, synthesize=synth)

            assert filename == "test_audio.mp3"
            assert os.path.exists(output_path)
            with open(output_path, "rb") as f:
                assert f.read() == mp3_data

    async def test_creates_parent_directory(self):
        synth = _fake_synthesize(b"\x00" * 100)

        with tempfile.TemporaryDirectory() as tmpdir:
            nested_path = os.path.join(tmpdir, "subdir", "deep", "test.mp3")
            await synthesize_to_file("Test", "voice_1", nested_path, synthesize=synth)
            assert os.path.exists(nested_path)

    async def test_handles_multiple_frames_concatenated(self):
        combined = b"\x01" * 100 + b"\x02" * 100
        synth = _fake_synthesize(combined)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "multi.mp3")
            await synthesize_to_file("Two frames", "voice_1", output_path, synthesize=synth)
            assert os.path.getsize(output_path) == 200

    async def test_rejects_relative_path_traversal(self):
        with pytest.raises(ValueError, match="Path traversal"):
            await synthesize_to_file("Hello", "voice_1", "/tmp/audio/../../../etc/passwd")

    async def test_rejects_absolute_path_traversal(self):
        with pytest.raises(ValueError, match="Path traversal"):
            await synthesize_to_file("Hello", "voice_1", "output/../../secret.mp3")

    async def test_returns_filename_only(self):
        synth = _fake_synthesize(b"\x00" * 10)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "activity_abc123.mp3")
            result = await synthesize_to_file("Test", "voice_1", output_path, synthesize=synth)
            assert result == "activity_abc123.mp3"
            assert "/" not in result

    async def test_passes_text_and_voice_to_synthesizer(self):
        calls = []

        async def _tracking_synth(text: str, voice_id: str) -> bytes:
            calls.append((text, voice_id))
            return b"\x00"

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test.mp3")
            await synthesize_to_file("Hello world", "MY_VOICE", output_path, synthesize=_tracking_synth)

        assert calls == [("Hello world", "MY_VOICE")]
