"""Guard for the story-002 wav->mp3 transcode helper (M22 compressed-bundle fold).

scripts/audio/generate_spell_sfx_stableaudio.py generates the committed spell-SFX
palette as .wav (Stable Audio 3.0 has no native mp3 encoder); `transcode_to_mp3`
shells out to ffmpeg to compress it to the bundle's .mp3 convention. Guarded
here (imported by file path, same pattern as test_generate_spell_sfx.py) so the
transcode contract stays under the fast lane without requiring torch.

Skips if ffmpeg isn't on PATH (mirrors the M17 capstone's bun-skip) so an
ffmpeg-less CI doesn't break the whole fast lane.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

_GENERATOR_PATH = Path(__file__).resolve().parents[3] / "scripts" / "audio" / "generate_spell_sfx_stableaudio.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_spell_sfx_stableaudio", _GENERATOR_PATH)
    assert spec and spec.loader, f"cannot load generator at {_GENERATOR_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_silent_wav(path: Path, *, duration_s: float = 0.5, sample_rate: int = 44100) -> None:
    """A too-short wav mp3-encodes LARGER than raw PCM (frame/header floor); use >=0.5s."""
    n_frames = int(duration_s * sample_rate)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * n_frames)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")
def test_transcode_to_mp3_produces_valid_mpeg_file(tmp_path: Path) -> None:
    gen = _load_generator()
    src_wav = tmp_path / "silence.wav"
    dst_mp3 = tmp_path / "silence.mp3"
    _write_silent_wav(src_wav)

    gen.transcode_to_mp3(src_wav, dst_mp3)

    assert dst_mp3.exists()
    data = dst_mp3.read_bytes()
    assert len(data) > 0
    header = data[:3]
    is_mpeg_frame_sync = data[0] == 0xFF and (data[1] & 0xE0) == 0xE0
    is_id3_tag = header == b"ID3"
    assert is_mpeg_frame_sync or is_id3_tag, f"not a valid mp3: first bytes {data[:8]!r}"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")
def test_transcode_to_mp3_raises_on_missing_source(tmp_path: Path) -> None:
    gen = _load_generator()
    with pytest.raises((subprocess.CalledProcessError, FileNotFoundError)):
        gen.transcode_to_mp3(tmp_path / "does_not_exist.wav", tmp_path / "out.mp3")
