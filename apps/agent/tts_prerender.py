"""TTS audio pre-rendering via the Inworld REST API.

Calls the Inworld TTS streaming endpoint directly instead of going through
the LiveKit plugin, so it works outside a LiveKit agent job context
(e.g. from the async_worker process or offline scripts).
"""

import base64
import contextlib
import json
import logging
import os
import subprocess
import tempfile
from collections.abc import AsyncIterator, Callable, Coroutine
from functools import partial

import aiohttp

logger = logging.getLogger("divineruin.tts_prerender")

INWORLD_BASE_URL = os.environ.get("INWORLD_BASE_URL", "https://api.inworld.ai")
INWORLD_MODEL = "inworld-tts-1"

# Type alias for the TTS synthesizer function
SynthesizeFn = Callable[[str, str], Coroutine[None, None, bytes]]


async def inworld_tts(
    text: str,
    voice_id: str,
    *,
    session: aiohttp.ClientSession | None = None,
) -> bytes:
    """Call the Inworld TTS API and return raw MP3 bytes.

    Pass a shared ``session`` to reuse connections across multiple calls.
    """
    api_key = os.environ.get("INWORLD_API_KEY")
    if not api_key:
        raise RuntimeError("INWORLD_API_KEY not set")

    payload = {
        "text": text,
        "voiceId": voice_id,
        "modelId": INWORLD_MODEL,
        "audioConfig": {
            "audioEncoding": "MP3",
            "sampleRateHertz": 44100,
        },
    }

    async def _do_request(s: aiohttp.ClientSession) -> bytes:
        mp3_data = bytearray()
        async with s.post(
            f"{INWORLD_BASE_URL}/tts/v1/voice:stream",
            headers={
                "Authorization": f"Basic {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=aiohttp.ClientTimeout(total=120, connect=10),
        ) as resp:
            if resp.status != 200:
                resp_text = await resp.text()
                raise RuntimeError(f"Inworld TTS failed ({resp.status}): {resp_text}")
            async for raw_line in resp.content:
                line = raw_line.strip()
                if not line:
                    continue
                data = json.loads(line)
                if error := data.get("error"):
                    raise RuntimeError(f"Inworld TTS error: {error.get('message', error)}")
                if (result := data.get("result")) and (audio := result.get("audioContent")):
                    mp3_data.extend(base64.b64decode(audio))
        if not mp3_data:
            raise RuntimeError("Inworld TTS returned no audio data")
        return bytes(mp3_data)

    if session:
        return await _do_request(session)

    async with aiohttp.ClientSession() as s:
        return await _do_request(s)


@contextlib.asynccontextmanager
async def tts_session() -> AsyncIterator[SynthesizeFn]:
    """Yield a TTS synthesizer backed by a shared HTTP session.

    Use this when making multiple TTS calls to avoid per-call TCP/TLS overhead::

        async with tts_session() as synth:
            await synthesize_to_file(text, voice, path, synthesize=synth)
    """
    async with aiohttp.ClientSession() as session:
        yield partial(inworld_tts, session=session)


def _reencode_mp3(raw_mp3: bytes) -> bytes:
    """Re-encode raw MP3 bytes through ffmpeg to fix invalid frame headers.

    The Inworld streaming API returns chunks that, when concatenated, can
    produce malformed MP3 files.  A quick ffmpeg pass produces a clean file
    that strict decoders (like PyAV) can handle.
    """
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_in:
        tmp_in.write(raw_mp3)
        tmp_in_path = tmp_in.name

    tmp_out_path = tmp_in_path.replace(".mp3", "_clean.mp3")
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                tmp_in_path,
                "-c:a",
                "libmp3lame",
                "-b:a",
                "128k",
                tmp_out_path,
            ],
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning("ffmpeg re-encode failed, using raw bytes: %s", result.stderr[-200:])
            return raw_mp3

        with open(tmp_out_path, "rb") as f:
            return f.read()
    finally:
        for p in (tmp_in_path, tmp_out_path):
            with contextlib.suppress(OSError):
                os.unlink(p)


async def synthesize_to_file(
    text: str,
    voice_id: str,
    output_path: str,
    *,
    synthesize: SynthesizeFn = inworld_tts,
) -> str:
    """Synthesize text to an MP3 file.

    Returns the filename (not full path) for URL construction.
    Pass a custom ``synthesize`` callable for testing.
    """
    if ".." in output_path:
        raise ValueError(f"Path traversal not allowed in output_path: {output_path}")

    mp3_data = await synthesize(text, voice_id)
    mp3_data = _reencode_mp3(mp3_data)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(mp3_data)

    filename = os.path.basename(output_path)
    logger.info("Audio rendered: %s (%d bytes)", filename, len(mp3_data))

    return filename
