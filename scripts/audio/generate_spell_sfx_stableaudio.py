#!/usr/bin/env python3
"""Generate the M17 spell-cast SFX palette with Stable Audio 3.0 Small SFX (story-002 bake-off).

Free/open-weight counterpart to generate_spell_sfx.py (ElevenLabs), for the
quality bake-off: same frozen 7-key prompt table, a different engine, so the
customer can A/B them and pick the vendor — preferring this one if it clears the
bar (no subscription, self-hosted, Stability AI Community License).

Reuses the PROMPTS table and out_path helper from generate_spell_sfx.py (the
single prompt SSOT); this script's model renders raw .wav, then `transcode_to_mp3`
(ffmpeg, no torch) compresses it to the bundle's .mp3 convention (--format mp3,
the default). Requires the `stable-audio-3` package + torch/torchaudio in a
DEDICATED venv (not a repo dependency) and a HuggingFace token with the model's
gated terms accepted:

    uv venv /tmp/sa3 --python 3.11 && /tmp/sa3/bin/pip install stable-audio-3
    /tmp/sa3/bin/python scripts/audio/generate_spell_sfx_stableaudio.py --out-dir /tmp/bakeoff/stableaudio

Model: stabilityai/stable-audio-3-small-sfx (open weights, ~433M params, CPU/MPS).
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_GENERATOR_PATH = _THIS_DIR / "generate_spell_sfx.py"
_MODEL_NAME = "small-sfx"
_SAMPLE_RATE = 44100


def _load_generator():
    """Import the ElevenLabs generator module for its frozen PROMPTS table + out_path helper (the shared SSOT)."""
    spec = importlib.util.spec_from_file_location("generate_spell_sfx", _GENERATOR_PATH)
    assert spec and spec.loader, f"cannot load {_GENERATOR_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def transcode_to_mp3(src_wav: Path, dst_mp3: Path, *, bitrate: str = "128k") -> None:
    """Compress a wav to mp3 via ffmpeg (torch-free, fast-lane testable).

    Strips encoder metadata (-map_metadata -1) so the output is otherwise
    deterministic for a given input; ffmpeg's mp3 bytes themselves are not
    byte-reproducible across runs, so callers that need a byte-identical
    source/bundled pair must transcode once and copy the file, not re-run this.
    Raises on any ffmpeg failure (fail loud, no silent skip).
    """
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(src_wav),
            "-map_metadata",
            "-1",
            "-b:a",
            bitrate,
            str(dst_mp3),
        ],
        check=True,
        capture_output=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the spell-cast palette via Stable Audio 3.0 Small SFX.")
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--keys", nargs="*", help="subset of palette keys (default: all 7)")
    parser.add_argument("--variants", type=int, default=1, help="takes per key (default 1)")
    parser.add_argument("--duration", type=float, default=2.0, help="seconds")
    parser.add_argument(
        "--format",
        choices=("wav", "mp3"),
        default="mp3",
        help="mp3 (default) transcodes+removes the rendered wav via ffmpeg; wav keeps the raw SA3 output",
    )
    args = parser.parse_args(argv)

    generator = _load_generator()
    prompts = generator.PROMPTS
    keys = args.keys or sorted(prompts)
    unknown = [k for k in keys if k not in prompts]
    if unknown:
        parser.error(f"unknown keys: {unknown}. Valid: {sorted(prompts)}")

    # Imported lazily so the pure prompt-loading path stays importable without torch.
    import torchaudio  # type: ignore
    from stable_audio_3 import StableAudioModel  # type: ignore

    print(f"loading stabilityai/stable-audio-3-{_MODEL_NAME} ...")
    model = StableAudioModel.from_pretrained(_MODEL_NAME)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for key in keys:
        for v in range(1, args.variants + 1):
            final_ext = ".mp3" if args.format == "mp3" else ".wav"
            final_path = generator.out_path(args.out_dir, key, v, args.variants, ext=final_ext)
            if final_path.exists():
                print(f"skip (exists): {final_path}")
                continue
            wav_path = final_path if args.format == "wav" else final_path.with_suffix(".wav")
            audio = model.generate(prompt=prompts[key], duration=args.duration)
            # torchaudio.save wants a 2-D [channels, frames] tensor; squeeze a leading batch dim.
            if hasattr(audio, "dim") and audio.dim() == 3:
                audio = audio.squeeze(0)
            # Int16 PCM (not the tensor's native Float32): half the size and the
            # widely-supported format for the Expo/expo-audio bundle (ExoPlayer/AVAudioPlayer).
            torchaudio.save(
                str(wav_path),
                audio.cpu(),
                sample_rate=_SAMPLE_RATE,
                encoding="PCM_S",
                bits_per_sample=16,
            )
            print(f"wrote {wav_path}")
            if args.format == "mp3":
                transcode_to_mp3(wav_path, final_path)
                wav_path.unlink()
                print(f"transcoded -> {final_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
