"""Guard: no uncommitted .wav bloat in the bundled or source spell-SFX palettes (M22).

M22 requires all bundled audio to ship compressed. Debt 4e6fe7870edd: the 7
spell-cast SFX shipped as uncommitted-compressed 16-bit PCM .wav (~2.4MB,
committed twice, source + bundled), breaking the ~50-72KB .mp3 convention used
by every other bundled sound. This guard fails loud if a .wav ever reappears
under either directory. Regeneration stories 003-005 do not flip this scope
(decision audio-compression-guard-scope) — story-006 extends it later.
"""

from __future__ import annotations

from pathlib import Path

# This file lives at apps/agent/tests/<this>; parents[2] is the repo's apps/ dir.
_APPS_DIR = Path(__file__).resolve().parents[2]
_SOUNDS_DIR = _APPS_DIR / "mobile" / "assets" / "sounds"
_AUDIO_SRC_DIR = _APPS_DIR / "audio" / "spell_sfx"


def test_no_wav_files_in_bundled_sounds_dir() -> None:
    wavs = sorted(_SOUNDS_DIR.glob("*.wav"))
    assert not wavs, f"uncompressed .wav found in bundled sounds dir: {wavs}"


def test_no_wav_files_in_spell_sfx_source_dir() -> None:
    wavs = sorted(_AUDIO_SRC_DIR.glob("*.wav"))
    assert not wavs, f"uncompressed .wav found in spell_sfx source dir: {wavs}"
