"""Guard: no uncommitted .wav bloat in the bundled or source spell-SFX palettes (M22).

M22 requires all bundled audio to ship compressed. Debt 4e6fe7870edd: the 7
spell-cast SFX shipped as uncommitted-compressed 16-bit PCM .wav (~2.4MB,
committed twice, source + bundled), breaking the ~50-72KB .mp3 convention used
by every other bundled sound. This guard fails loud if a .wav ever reappears
under either directory. Regeneration stories 003-005 do not flip this scope
(decision audio-compression-guard-scope) — story-006 extends it later.
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

# story-003 file_domain: the 20 legacy stems regenerated via SA3 + transcode_to_mp3.
_LEGACY_SA3_KEYS = (
    "arrow_loose",
    "critical_hit_sting",
    "dice_roll",
    "discovery_chime",
    "door_creak",
    "fail_sting",
    "god_whisper_stinger",
    "hit_taken",
    "item_pickup",
    "level_up_sting",
    "menu_close",
    "menu_open",
    "notification",
    "potion_use",
    "quest_sting",
    "shield_block",
    "spell_cast",
    "success_sting",
    "sword_clash",
    "tavern",
)

# transcode_to_mp3 encodes 128k nominal (~132kbps actual); the hand-sourced
# takes it replaced ran ~198kbps, so this ceiling discriminates the swap
# (red before story-003's regeneration, green after).
_PIPELINE_MAX_BITRATE = 160_000
_PIPELINE_SAMPLE_RATE = 44_100


def test_no_wav_files_in_bundled_sounds_dir() -> None:
    wavs = sorted(_SOUNDS_DIR.glob("*.wav"))
    assert not wavs, f"uncompressed .wav found in bundled sounds dir: {wavs}"


def test_no_wav_files_in_spell_sfx_source_dir() -> None:
    wavs = sorted(_AUDIO_SRC_DIR.glob("*.wav"))
    assert not wavs, f"uncompressed .wav found in spell_sfx source dir: {wavs}"


def test_legacy_sa3_stems_match_pipeline_transcode_signature() -> None:
    """Discriminating story-003 acceptance (concern 5eae0258e48c): the regenerated

    legacy stems must carry the SA3 pipeline's transcode signature — 44.1kHz,
    <=160kbps — which the ~198kbps hand-sourced takes did not. Fails if any
    legacy stem regresses to a non-pipeline (hand-sourced) file.

    Fail-loud on missing ffprobe (no skip): this is an acceptance guard, and a
    skip would silently drop AC1's provenance enforcement (concern 2c0c3026b0e4).
    """
    if shutil.which("ffprobe") is None:
        pytest.fail(
            "ffprobe (ffmpeg) is required to enforce the legacy-SFX provenance guard — "
            "install it (brew install ffmpeg); skipping would silently drop AC1 enforcement"
        )
    for key in _LEGACY_SA3_KEYS:
        path = _SOUNDS_DIR / f"{key}.mp3"
        assert path.exists(), f"missing bundled legacy stem: {path}"
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
        assert sample_rate == _PIPELINE_SAMPLE_RATE, f"{key}: sample_rate {sample_rate}"
        assert bit_rate <= _PIPELINE_MAX_BITRATE, (
            f"{key}: bit_rate {bit_rate} exceeds the transcode_to_mp3 ceiling — "
            "looks hand-sourced, not SA3-pipeline output"
        )


# story-009 file_domain: the 11 ambient soundscapes regenerated via SA3 medium.
_SOUNDSCAPE_SA3_KEYS = (
    "dungeon_ancient_hum",
    "dungeon_resonance_deep",
    "guild_hall_bustle",
    "harbor_activity",
    "harbor_quiet",
    "hollow_wrongness",
    "market_bustle",
    "rural_town_uneasy",
    "tavern_busy",
    "temple_row_chanting",
    "wind_ruins",
)
_SOUNDSCAPES_DIR = _SOUNDS_DIR / "soundscapes"


def test_soundscape_stems_match_pipeline_transcode_signature() -> None:
    """Discriminating story-009 acceptance: the regenerated ambient soundscapes

    must carry the SA3 pipeline's transcode signature — 44.1kHz, <=160kbps —
    which the ~192kbps hand-sourced loops did not. Fails if any soundscape stem
    regresses to a non-pipeline (hand-sourced) file. Third member of the family
    guard (legacy/texture/soundscape); story-006 consolidates all into one
    parametrized guard.

    Fail-loud on missing ffprobe (no skip): a skip would silently drop the
    soundscape provenance enforcement.
    """
    if shutil.which("ffprobe") is None:
        pytest.fail(
            "ffprobe (ffmpeg) is required to enforce the soundscape provenance guard — "
            "install it (brew install ffmpeg); skipping would silently drop the check"
        )
    for key in _SOUNDSCAPE_SA3_KEYS:
        path = _SOUNDSCAPES_DIR / f"{key}.mp3"
        assert path.exists(), f"missing bundled soundscape stem: {path}"
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
        assert sample_rate == _PIPELINE_SAMPLE_RATE, f"{key}: sample_rate {sample_rate}"
        assert bit_rate <= _PIPELINE_MAX_BITRATE, (
            f"{key}: bit_rate {bit_rate} exceeds the transcode_to_mp3 ceiling — "
            "looks hand-sourced, not SA3-pipeline output"
        )


# story-005 file_domain: the 11 texture foley one-shots regenerated via SA3 small-sfx.
_TEXTURE_SA3_KEYS = (
    "bird_call_01",
    "bird_call_02",
    "bird_call_03",
    "branch_crack",
    "cart_wheel",
    "dog_bark_distant",
    "fire_crackle",
    "footstep_stone",
    "insect_buzz",
    "water_drip",
    "wind_gust",
)
_TEXTURES_DIR = _SOUNDS_DIR / "textures"


def test_texture_stems_match_pipeline_transcode_signature() -> None:
    """Discriminating story-005 acceptance (concern fc59229f86a0): the regenerated

    texture foley one-shots must carry the SA3 pipeline's transcode signature —
    44.1kHz, <=160kbps — which the ~198kbps hand-sourced takes did not. Fails if any
    texture stem regresses to a non-pipeline (hand-sourced) file. Mirrors the legacy
    guard above; story-006 consolidates both into one parametrized family guard.

    Fail-loud on missing ffprobe (no skip): a skip would silently drop the
    texture provenance enforcement.
    """
    if shutil.which("ffprobe") is None:
        pytest.fail(
            "ffprobe (ffmpeg) is required to enforce the texture-SFX provenance guard — "
            "install it (brew install ffmpeg); skipping would silently drop the check"
        )
    for key in _TEXTURE_SA3_KEYS:
        path = _TEXTURES_DIR / f"{key}.mp3"
        assert path.exists(), f"missing bundled texture stem: {path}"
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
        assert sample_rate == _PIPELINE_SAMPLE_RATE, f"{key}: sample_rate {sample_rate}"
        assert bit_rate <= _PIPELINE_MAX_BITRATE, (
            f"{key}: bit_rate {bit_rate} exceeds the transcode_to_mp3 ceiling — "
            "looks hand-sourced, not SA3-pipeline output"
        )
