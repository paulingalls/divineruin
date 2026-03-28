"""Tests for TTS pre-rendering module."""

import os
import tempfile
from unittest.mock import patch

import pytest

from tts_prerender import synthesize_to_file, synthesize_with_pauses

MP3_STUB = b"\xff\xfb" * 50


def _fake_synthesize(data: bytes):
    """Return a synthesize function that yields fixed data."""

    async def _synth(text: str, voice_id: str) -> bytes:
        return data

    return _synth


async def _stub_tts(text, voice_id, *, speaking_rate=1.0, session=None):
    return MP3_STUB


def _stub_silence(seconds):
    return b"\x00" * 50


def _patch_tts_and_silence(mock_tts=_stub_tts, mock_silence=_stub_silence):
    """Return combined patch context for inworld_tts and _generate_mp3_silence."""
    return (
        patch("tts_prerender.inworld_tts", mock_tts),
        patch("tts_prerender._generate_mp3_silence", mock_silence),
    )


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

    async def test_speaking_rate_used_when_no_custom_synthesize(self):
        calls = []

        async def _mock_tts(text, voice_id, *, speaking_rate=1.0, session=None):
            calls.append({"text": text, "voice_id": voice_id, "speaking_rate": speaking_rate})
            return MP3_STUB

        with (
            patch("tts_prerender.inworld_tts", _mock_tts),
            tempfile.TemporaryDirectory() as tmpdir,
        ):
            output_path = os.path.join(tmpdir, "test.mp3")
            await synthesize_to_file("Hello", "voice_1", output_path, speaking_rate=0.7)

        assert len(calls) == 1
        assert calls[0]["speaking_rate"] == 0.7

    async def test_custom_synthesize_ignores_speaking_rate(self):
        calls = []

        async def _custom(text: str, voice_id: str) -> bytes:
            calls.append((text, voice_id))
            return b"\x00" * 10

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test.mp3")
            await synthesize_to_file(
                "Hello",
                "voice_1",
                output_path,
                speaking_rate=0.5,
                synthesize=_custom,
            )

        assert calls == [("Hello", "voice_1")]


class TestSynthesizeWithPauses:
    async def test_splits_text_and_calls_tts_per_chunk(self):
        tts_calls = []

        async def _tracking_tts(text, voice_id, *, speaking_rate=1.0, session=None):
            tts_calls.append({"text": text, "speaking_rate": speaking_rate})
            return MP3_STUB

        p_tts, p_silence = _patch_tts_and_silence(mock_tts=_tracking_tts)
        with p_tts, p_silence, tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.mp3")
            await synthesize_with_pauses(
                "Hello world. Goodbye world.",
                "voice_1",
                path,
                speaking_rate=0.8,
            )

        assert len(tts_calls) == 2
        assert tts_calls[0]["text"] == "Hello world."
        assert tts_calls[1]["text"] == "Goodbye world."
        assert all(c["speaking_rate"] == 0.8 for c in tts_calls)

    async def test_inserts_silence_between_sentences(self):
        call_log = []

        async def _log_tts(text, voice_id, *, speaking_rate=1.0, session=None):
            call_log.append(("tts", text))
            return MP3_STUB

        def _log_silence(seconds):
            call_log.append(("silence", seconds))
            return b"\x00" * 50

        p_tts, p_silence = _patch_tts_and_silence(mock_tts=_log_tts, mock_silence=_log_silence)
        with p_tts, p_silence, tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.mp3")
            await synthesize_with_pauses("First. Second.", "v", path)

        silence_calls = [c for c in call_log if c[0] == "silence"]
        assert any(s[1] == 0.6 for s in silence_calls)

    async def test_paragraph_breaks_produce_longer_pause(self):
        call_log = []

        async def _log_tts(text, voice_id, *, speaking_rate=1.0, session=None):
            call_log.append(("tts", text))
            return MP3_STUB

        def _log_silence(seconds):
            call_log.append(("silence", seconds))
            return b"\x00" * 50

        p_tts, p_silence = _patch_tts_and_silence(mock_tts=_log_tts, mock_silence=_log_silence)
        with p_tts, p_silence, tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.mp3")
            await synthesize_with_pauses("Para one.\n\nPara two.", "v", path)

        silence_calls = [c for c in call_log if c[0] == "silence"]
        assert any(s[1] == 0.8 for s in silence_calls)

    async def test_writes_output_file(self):
        p_tts, p_silence = _patch_tts_and_silence()
        with p_tts, p_silence, tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "output.mp3")
            filename = await synthesize_with_pauses("Hello.", "v", path)

            assert filename == "output.mp3"
            assert os.path.exists(path)
            assert os.path.getsize(path) > 0

    async def test_rejects_path_traversal(self):
        with pytest.raises(ValueError, match="Path traversal"):
            await synthesize_with_pauses("Hello.", "v", "/tmp/../../../etc/passwd")

    async def test_caches_silence_durations(self):
        """Silence generation should be called once per unique duration, not per occurrence."""
        silence_gen_calls = []

        def _tracking_silence(seconds):
            silence_gen_calls.append(seconds)
            return b"\x00" * 50

        p_tts, p_silence = _patch_tts_and_silence(mock_silence=_tracking_silence)
        with p_tts, p_silence, tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.mp3")
            await synthesize_with_pauses("One. Two. Three.", "v", path)

        assert silence_gen_calls.count(0.6) == 1
