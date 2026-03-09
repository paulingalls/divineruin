#!/usr/bin/env python3
"""Generate the prologue narration audio using the Inworld TTS API directly.

The LiveKit Inworld plugin requires an agent job context, so this script
calls the Inworld REST API directly for offline audio generation.

Usage:
    cd apps/agent && uv run python ../../scripts/generate_prologue.py
"""

import asyncio
import base64
import json
import os
import sys

import aiohttp


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


# Load .env from project root
_load_env(os.path.join(os.path.dirname(__file__), "..", ".env"))

INWORLD_BASE_URL = "https://api.inworld.ai"

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


async def synthesize(text: str, voice_id: str) -> bytes:
    """Call the Inworld TTS API directly and return MP3 bytes."""
    api_key = os.environ.get("INWORLD_API_KEY")
    if not api_key:
        print("ERROR: INWORLD_API_KEY not set")
        sys.exit(1)

    payload = {
        "text": text,
        "voiceId": voice_id,
        "modelId": "inworld-tts-1",
        "audioConfig": {
            "audioEncoding": "MP3",
            "sampleRateHertz": 44100,
            "speakingRate": 0.8,
        },
    }

    mp3_data = bytearray()
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{INWORLD_BASE_URL}/tts/v1/voice:stream",
            headers={
                "Authorization": f"Basic {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=aiohttp.ClientTimeout(total=120),
        ) as resp:
            if resp.status != 200:
                resp_text = await resp.text()
                print(f"HTTP {resp.status}: {resp_text}")
                sys.exit(1)
            async for raw_line in resp.content:
                line = raw_line.strip()
                if not line:
                    continue
                data = json.loads(line)
                if error := data.get("error"):
                    print(f"API error: {error.get('message', error)}")
                    sys.exit(1)
                if result := data.get("result"):
                    if audio := result.get("audioContent"):
                        mp3_data.extend(base64.b64decode(audio))

    return bytes(mp3_data)


async def main() -> None:
    voice_id = os.environ.get("INWORLD_VOICE_DM")
    if not voice_id:
        print("ERROR: INWORLD_VOICE_DM not set in environment")
        sys.exit(1)

    output_path = os.path.join(AUDIO_DIR, "prologue.mp3")
    print(f"Voice: {voice_id}")
    print(f"Output: {output_path}")
    print(f"Text: {len(PROLOGUE_TEXT)} chars, {len(PROLOGUE_TEXT.split())} words")

    mp3_data = await synthesize(PROLOGUE_TEXT, voice_id)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(mp3_data)

    print(f"Done! {os.path.basename(output_path)} ({len(mp3_data):,} bytes)")


if __name__ == "__main__":
    asyncio.run(main())
