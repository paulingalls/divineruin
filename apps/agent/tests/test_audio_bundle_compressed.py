"""Compressed takes keep bundled audio small."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from audio_bundle_stems import bundled_stems_by_dir

from spells import SPELL_SOUND_KEYS

_APPS_DIR = Path(__file__).resolve().parents[2]
_SOUNDS_DIR = _APPS_DIR / "mobile" / "assets" / "sounds"
_AUDIO_SRC_DIR = _APPS_DIR / "audio" / "spell_sfx"

# transcode_to_mp3 encodes 128k nominal (~132kbps actual); the hand-sourced
# takes it replaced ran ~192-198kbps, so this ceiling discriminates the swap
# (red before regeneration, green after) across every family.
_PIPELINE_MAX_BITRATE = 160_000
_PIPELINE_SAMPLE_RATE = 44_100


def test_no_wav_files_in_bundled_sounds_dir() -> None:
    wavs = sorted(_SOUNDS_DIR.glob("**/*.wav"))
    assert not wavs, f"uncompressed .wav found in bundled sounds dir: {wavs}"


def test_no_wav_files_in_spell_sfx_source_dir() -> None:
    wavs = sorted(_AUDIO_SRC_DIR.glob("*.wav"))
    assert not wavs, f"uncompressed .wav found in spell_sfx source dir: {wavs}"


# Source dirs whose committed .mp3s must stay byte-identical to a bundled family dir.
# The regenerate pipeline writes both copies; nothing else asserts they match, so a
# regen that updates the source and forgets the bundled copy (or vice versa) would ship
# stale audio while every other lane stays green. Fail loud on that drift. (Sole owner
# of this assertion after story-006 removed the capstone's byte-equality copy.)
#
# Each mirror also pins the FULL expected source key-set: the byte-equal loop globs
# only files that exist, so a *deleted* source take would silently pass (the glob just
# omits it, the byte-equal check never sees it, and the M17 capstone only checks the
# still-present bundled copy). The key-set assertion below is what actually enforces
# that every customer-approved take is still on disk in the source SSOT.
_SOURCE_MIRRORS: dict[Path, tuple[Path, frozenset[str]]] = {
    _AUDIO_SRC_DIR: (_SOUNDS_DIR, SPELL_SOUND_KEYS),
}


def test_committed_source_mirror_is_byte_equal_to_bundled() -> None:
    for source_dir, (bundled_dir, expected_keys) in _SOURCE_MIRRORS.items():
        sources = sorted(source_dir.glob("*.mp3"))
        source_stems = {src.stem for src in sources}
        missing = sorted(expected_keys - source_stems)
        assert not missing, (
            f"source palette under {source_dir} is missing keys {missing} -- a deleted "
            "source take passes the byte-equal glob silently; the source SSOT must hold "
            "every approved take"
        )
        for src in sources:
            bundled = bundled_dir / src.name
            assert bundled.exists(), f"bundled mirror missing: {bundled}"
            assert src.read_bytes() == bundled.read_bytes(), (
                f"{src.name} differs between source ({src}) and bundled ({bundled}) -- regenerate both"
            )


def _probe(path: Path) -> tuple[int, int]:
    """Return (sample_rate, bit_rate) for an audio file via ffprobe."""
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=sample_rate:format=bit_rate",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    info = json.loads(probe.stdout)
    sample_rate = int(info["streams"][0]["sample_rate"])
    bit_rate = int(info["format"]["bit_rate"])
    return sample_rate, bit_rate


_FAMILY_DIRS = sorted(bundled_stems_by_dir(_SOUNDS_DIR).keys())


@pytest.mark.parametrize("family_dir", _FAMILY_DIRS)
def test_bundled_family_stems_match_pipeline_transcode_signature(family_dir: str) -> None:
    """Missing ffprobe must fail rather than silently skip audio validation."""
    if shutil.which("ffprobe") is None:
        pytest.fail(
            "ffprobe (ffmpeg) is required to enforce the transcode-signature provenance guard — "
            "install it (brew install ffmpeg); skipping would silently drop enforcement"
        )
    base = _SOUNDS_DIR if family_dir == "." else _SOUNDS_DIR / family_dir
    stems = bundled_stems_by_dir(_SOUNDS_DIR)[family_dir]
    for key in sorted(stems):
        path = base / f"{key}.mp3"
        assert path.exists(), f"missing bundled stem: {path}"
        sample_rate, bit_rate = _probe(path)
        assert sample_rate == _PIPELINE_SAMPLE_RATE, f"{family_dir}/{key}: sample_rate {sample_rate}"
        assert bit_rate <= _PIPELINE_MAX_BITRATE, (
            f"{family_dir}/{key}: bit_rate {bit_rate} exceeds the transcode_to_mp3 ceiling — "
            "looks hand-sourced, not SA3-pipeline output"
        )
