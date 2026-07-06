#!/usr/bin/env python3
"""Generate the M17 spell-cast SFX palette via ElevenLabs Text-to-Sound (story-002).

The 7-key source-by-effect palette is frozen in docs/audio_sfx_pipeline.md §4 and
guarded by apps/agent/tests/test_generate_spell_sfx.py. This is the ElevenLabs
(.mp3) bake-off generator, and it owns the shared PROMPTS table + _out_path helper
— the single prompt SSOT that generate_spell_sfx_stableaudio.py imports.

NOTE ON THE COMMITTED PALETTE: the shipped assets are the .wav files produced by
generate_spell_sfx_stableaudio.py (Stable Audio 3.0 Small SFX), the vendor that
won the story-002 bake-off. To REGENERATE the committed palette, run that script,
not this one. Use this ElevenLabs generator for A/B comparison or as the
alternative engine — both share the frozen prompts, so they stay comparable ("Audio
Must Be Generatable"; regeneration is generative, not byte-for-byte).

Stdlib only (urllib) — no third-party deps. Reads ELEVEN_LABS_API_KEY from the
environment (fail-loud), the only external input.

Usage:
    export ELEVEN_LABS_API_KEY=...            # or `source ~/.zprofile`
    python scripts/audio/generate_spell_sfx.py --out-dir apps/audio/spell_sfx
    python scripts/audio/generate_spell_sfx.py --out-dir /tmp/bakeoff --variants 2
    python scripts/audio/generate_spell_sfx.py --keys spell_nature spell_radiant
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

# The frozen 7-key palette. Prompts for the four "direct" keys carry the
# CMB-006/007/008/009 language from the prior harness
# (~/src/clones/stable-audio-tools/generate_divine_ruin.py); the last three are
# new casts (radiant/nature/generic) that had no prior prompt. Each is tuned as a
# short, dry, punchy game SFX so it lands in the gaps between DM narration.
PROMPTS: dict[str, str] = {
    "spell_fire": (
        "Fantasy fire spell being cast and released. A soft inward whoosh as energy "
        "gathers, then a sharp ignition crack and a brief roar of expanding flame that "
        "fades to a dissipating crackle. Explosive magical release, not a sustained "
        "burn. Short, punchy game sound effect, dry, no music."
    ),
    "spell_ice": (
        "Fantasy ice spell being cast and released. A high glassy hiss as the air "
        "freezes, a sharp crystalline crack like rich shattering glass, then a brittle "
        "scatter of ice shards. High and bright, cold and precise. Short, punchy game "
        "sound effect, dry, no music."
    ),
    "spell_arcane_force": (
        "Fantasy arcane force spell being discharged. A low subsonic hum building "
        "rapidly in pitch, releasing as a concussive low-frequency thump felt in the "
        "chest, then a brief whoosh of displaced air. Heavy, low-mid, it pushes rather "
        "than crackles. Short, punchy game sound effect, dry, no music."
    ),
    "spell_heal": (
        "Fantasy healing spell activating. Soft and warm: a gentle rising tone like a "
        "quiet choir note from silence, releasing into a warm chime with a resonant "
        "shimmering tail. High-mid, no bass, kind and relieving. Short game sound "
        "effect, dry, no music."
    ),
    "spell_radiant": (
        "Fantasy divine radiant spell being cast, a smite of holy light. A warm "
        "ascending cathedral-like chime with a golden shimmer, releasing as a clean "
        "resonant burst of radiance. Authoritative and holy, not a heal. Short, punchy "
        "game sound effect, dry, no music."
    ),
    "spell_nature": (
        "Fantasy primal nature spell being cast. Sudden organic growth: rustling earth, "
        "cracking wood, and whipping vines and thorns erupting, with a green living "
        "texture. Earthy and alive. Short, punchy game sound effect, dry, no music."
    ),
    "spell_generic": (
        "A generic fantasy magic spell being cast. A neutral arcane shimmer and whoosh "
        "with a soft chime as energy gathers and releases, no specific element. Short "
        "game sound effect, dry, no music."
    ),
}

_API_URL = "https://api.elevenlabs.io/v1/sound-generation"
_MODEL_ID = "eleven_text_to_sound_v2"
_OUTPUT_FORMAT = "mp3_44100_128"
_ENV_KEY = "ELEVEN_LABS_API_KEY"


def _require_api_key() -> str:
    key = os.environ.get(_ENV_KEY, "").strip()
    if not key:
        sys.exit(f"{_ENV_KEY} is not set. `source ~/.zprofile` (or export it) before running.")
    return key


def _generate_one(text: str, *, duration: float, prompt_influence: float, loop: bool, api_key: str) -> bytes:
    """POST one prompt to ElevenLabs and return the MP3 bytes. Fail-loud on any HTTP error."""
    body = json.dumps(
        {
            "text": text,
            "duration_seconds": duration,
            "prompt_influence": prompt_influence,
            "loop": loop,
            "model_id": _MODEL_ID,
        }
    ).encode()
    req = urllib.request.Request(
        f"{_API_URL}?output_format={_OUTPUT_FORMAT}",
        data=body,
        method="POST",
        headers={
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        sys.exit(f"ElevenLabs HTTP {e.code} for prompt: {text[:60]!r}...\n{detail}")


def out_path(out_dir: Path, key: str, variant: int, total_variants: int, ext: str = ".mp3") -> Path:
    """Shared palette-file namer. ext is the engine's format (.mp3 here, .wav for Stable Audio)."""
    name = f"{key}{ext}" if total_variants == 1 else f"{key}_v{variant}{ext}"
    return out_dir / name


def generate(
    keys: list[str],
    out_dir: Path,
    *,
    variants: int,
    duration: float,
    prompt_influence: float,
    loop: bool,
) -> list[Path]:
    """Generate the requested palette keys into out_dir. Idempotent: skips existing files."""
    api_key = _require_api_key()
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for key in keys:
        prompt = PROMPTS[key]
        for v in range(1, variants + 1):
            path = out_path(out_dir, key, v, variants)
            if path.exists():
                print(f"skip (exists): {path}")
                continue
            audio = _generate_one(
                prompt,
                duration=duration,
                prompt_influence=prompt_influence,
                loop=loop,
                api_key=api_key,
            )
            path.write_bytes(audio)
            print(f"wrote {path} ({len(audio)} bytes)")
            written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the M17 spell-cast SFX palette.")
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument(
        "--keys",
        nargs="*",
        default=sorted(PROMPTS),
        help="subset of palette keys (default: all 7)",
    )
    parser.add_argument("--variants", type=int, default=1, help="takes per key (default 1)")
    parser.add_argument("--duration", type=float, default=2.0, help="seconds, 0.5-30")
    parser.add_argument("--prompt-influence", type=float, default=0.5)
    parser.add_argument("--loop", action="store_true", help="request a seamless loop")
    args = parser.parse_args(argv)

    unknown = [k for k in args.keys if k not in PROMPTS]
    if unknown:
        parser.error(f"unknown keys: {unknown}. Valid: {sorted(PROMPTS)}")

    generate(
        args.keys,
        args.out_dir,
        variants=args.variants,
        duration=args.duration,
        prompt_influence=args.prompt_influence,
        loop=args.loop,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
