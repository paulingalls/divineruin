"""Guard: no uncommitted .wav bloat, drift-free transcode signature across bundled families (M22).

M22 requires all bundled audio to ship compressed. Debt 4e6fe7870edd: the 7
spell-cast SFX shipped as uncommitted-compressed 16-bit PCM .wav (~2.4MB,
committed twice, source + bundled), breaking the ~50-72KB .mp3 convention used
by every other bundled sound. This guard fails loud if a .wav ever reappears
under either directory.

Story-006 consolidated the three per-family (legacy/soundscape/texture) hand-
maintained transcode-signature guards into one directory-driven, parametrized
guard covering every bundled family (root, music, soundscapes, textures) --
the stem set is discovered from the bundled directory listing, not a
hand-maintained tuple, so a new regenerated family auto-extends coverage.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

# This file lives at apps/agent/tests/<this>; parents[2] is the repo's apps/ dir.
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


def _bundled_stems_by_dir() -> dict[str, set[str]]:
    """Map each family dir (top-level '.' plus each subdir name) to its stem set."""
    families: dict[str, set[str]] = {}
    for path in _SOUNDS_DIR.glob("**/*"):
        if path.suffix not in (".mp3", ".wav"):
            continue
        family = path.parent.relative_to(_SOUNDS_DIR).as_posix()
        families.setdefault(family, set()).add(path.stem)
    return families


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


# Discovered at collection time from the bundled directory listing -- covers root
# (legacy 20 + 7 spell stems), music, soundscapes, textures with no hand-maintained
# key tuple. A future regenerated family auto-extends this parametrization.
_FAMILY_DIRS = sorted(_bundled_stems_by_dir().keys())


@pytest.mark.parametrize("family_dir", _FAMILY_DIRS)
def test_bundled_family_stems_match_pipeline_transcode_signature(family_dir: str) -> None:
    """Every bundled stem in every family must carry the SA3 pipeline's transcode

    signature -- 44.1kHz, <=160kbps -- which hand-sourced takes did not. Fails if
    any stem regresses to a non-pipeline (hand-sourced) file.

    Fail-loud on missing ffprobe (no skip): this is an acceptance guard, and a
    skip would silently drop the provenance enforcement (concern 2c0c3026b0e4).
    """
    if shutil.which("ffprobe") is None:
        pytest.fail(
            "ffprobe (ffmpeg) is required to enforce the transcode-signature provenance guard — "
            "install it (brew install ffmpeg); skipping would silently drop enforcement"
        )
    base = _SOUNDS_DIR if family_dir == "." else _SOUNDS_DIR / family_dir
    stems = _bundled_stems_by_dir()[family_dir]
    for key in sorted(stems):
        path = base / f"{key}.mp3"
        assert path.exists(), f"missing bundled stem: {path}"
        sample_rate, bit_rate = _probe(path)
        assert sample_rate == _PIPELINE_SAMPLE_RATE, f"{family_dir}/{key}: sample_rate {sample_rate}"
        assert bit_rate <= _PIPELINE_MAX_BITRATE, (
            f"{family_dir}/{key}: bit_rate {bit_rate} exceeds the transcode_to_mp3 ceiling — "
            "looks hand-sourced, not SA3-pipeline output"
        )
