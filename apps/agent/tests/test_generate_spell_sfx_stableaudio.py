"""Stable Audio has no MP3 encoder; ffmpeg transcodes its WAV output without requiring torch here.
The existing cases skip when ffmpeg is unavailable."""

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


def test_parser_defaults_pin_the_approved_m17_recipe() -> None:
    """Use the clipped recipe to exercise audible saturation."""
    gen = _load_generator()
    args = gen.build_parser().parse_args(["--out-dir", "/tmp/unused"])
    assert args.steps == 8
    assert args.cfg_scale == 1.0
    assert args.duration == 2.0
    assert args.format == "mp3"


def test_model_selector_defaults_to_small_sfx_and_accepts_music_models() -> None:
    """Use the installed Stable Audio model registry; guessed keys fail only at load time."""
    gen = _load_generator()
    default = gen.build_parser().parse_args(["--out-dir", "/tmp/unused"])
    assert default.model == "small-sfx"
    for name in ("small-sfx", "small-music", "medium"):
        args = gen.build_parser().parse_args(["--out-dir", "/tmp/unused", "--model", name])
        assert args.model == name
    with pytest.raises(SystemExit):
        gen.build_parser().parse_args(["--out-dir", "/tmp/unused", "--model", "not-a-model"])


def test_device_selector_defaults_to_auto_and_accepts_mps_and_cpu() -> None:
    """The MPS backend can exhaust memory where CPU succeeds."""
    gen = _load_generator()
    default = gen.build_parser().parse_args(["--out-dir", "/tmp/unused"])
    assert default.device == "auto"
    for name in ("auto", "mps", "cpu"):
        args = gen.build_parser().parse_args(["--out-dir", "/tmp/unused", "--device", name])
        assert args.device == name
    with pytest.raises(SystemExit):
        gen.build_parser().parse_args(["--out-dir", "/tmp/unused", "--device", "cuda:0"])


class _FakeTensor:
    """Duck-types the one tensor method the noise guard uses (torch-free lane)."""

    def __init__(self, std: float) -> None:
        self._std = std

    def std(self) -> float:
        return self._std


def test_noise_guard_rejects_clamped_gaussian_renders() -> None:
    """Clamped noise can conceal invalid generated audio."""
    gen = _load_generator()
    with pytest.raises(RuntimeError, match="noise"):
        gen.assert_take_is_not_noise(_FakeTensor(0.83), "spell_fire")


def test_noise_guard_passes_normal_renders() -> None:
    gen = _load_generator()
    gen.assert_take_is_not_noise(_FakeTensor(0.05), "spell_fire")


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
