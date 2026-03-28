#!/usr/bin/env python3
"""Generate the prologue narration audio using Inworld TTS.

Usage:
    cd apps/agent && uv run python ../../scripts/generate_prologue.py
"""

import asyncio
import os
import sys

# Add agent directory to path so we can import tts_prerender
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "agent"))


def _load_env(path: str) -> None:
    """Minimal .env loader — no external dependency needed."""
    if not os.path.isfile(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key.strip(), value)


# Load .env from project root (must happen before importing agent modules)
_load_env(os.path.join(os.path.dirname(__file__), "..", ".env"))

from tts_prerender import synthesize_with_pauses  # noqa: E402
from voices import get_voice_config  # noqa: E402

AUDIO_DIR = os.environ.get(
    "ASYNC_AUDIO_DIR",
    os.path.join(os.path.dirname(__file__), "..", "apps", "server", "audio"),
)

PROLOGUE_TEXT = (
    "Before the breaking, Aethos was whole. "
    "A world shaped by gods who walked among their creation — "
    "tending forests, stirring oceans, whispering through the wind. "
    "At its heart stood Aelindra, the jeweled city, "
    "where mortal and divine wove knowledge into the fabric of reality itself. "
    "\n\n"
    "Then the Veil cracked. "
    "No army marched through. No conqueror claimed the breach. "
    "Something far worse seeped in — formless, patient, and without mind. "
    "The Hollow. An anti-reality that unmakes everything it touches. "
    "Aelindra fell in a single night. "
    "Where the city once shone, only the Voidmaw remains — "
    "a wound in the world that will not close. "
    "\n\n"
    "That was thirty years ago. "
    "The gods still stand, but they are divided. "
    "Some seek to reclaim what was lost. Others would seal the wound and accept the cost. "
    "The peoples of Aethos have scattered to the edges, "
    "building new lives in the shadow of slow extinction. "
    "\n\n"
    "And now, something stirs. "
    "A soul adrift between worlds begins to take shape — "
    "drawn by forces not yet understood. "
    "The gods are watching. "
    "Your story is about to begin."
)


async def main() -> None:
    voice_cfg = get_voice_config("DM_NARRATOR", "calm")
    if not voice_cfg.voice:
        print("ERROR: INWORLD_VOICE_DM not set in environment")
        sys.exit(1)

    output_path = os.path.join(AUDIO_DIR, "prologue.mp3")
    print(f"Voice: {voice_cfg.voice} (rate: {voice_cfg.speaking_rate})")
    print(f"Output: {output_path}")
    print(f"Text: {len(PROLOGUE_TEXT)} chars, {len(PROLOGUE_TEXT.split())} words")

    await synthesize_with_pauses(
        PROLOGUE_TEXT,
        voice_cfg.voice,
        output_path,
        speaking_rate=voice_cfg.speaking_rate,
    )

    file_size = os.path.getsize(output_path)
    print(f"Done! {os.path.basename(output_path)} ({file_size:,} bytes)")


if __name__ == "__main__":
    asyncio.run(main())
