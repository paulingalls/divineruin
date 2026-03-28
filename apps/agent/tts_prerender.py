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

from tts_pauses import chunk_text_with_pauses

logger = logging.getLogger("divineruin.tts_prerender")

INWORLD_BASE_URL = os.environ.get("INWORLD_BASE_URL", "https://api.inworld.ai")
INWORLD_MODEL = "inworld-tts-1"

# Type alias for the TTS synthesizer function
SynthesizeFn = Callable[[str, str], Coroutine[None, None, bytes]]


async def inworld_tts(
    text: str,
    voice_id: str,
    *,
    speaking_rate: float = 1.0,
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
            "speakingRate": speaking_rate,
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
async def tts_session(speaking_rate: float = 1.0) -> AsyncIterator[SynthesizeFn]:
    """Yield a TTS synthesizer backed by a shared HTTP session.

    Use this when making multiple TTS calls to avoid per-call TCP/TLS overhead::

        async with tts_session(speaking_rate=0.8) as synth:
            await synthesize_to_file(text, voice, path, synthesize=synth)
    """
    async with aiohttp.ClientSession() as session:
        yield partial(inworld_tts, session=session, speaking_rate=speaking_rate)


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


def _validate_output_path(output_path: str) -> None:
    if ".." in output_path:
        raise ValueError(f"Path traversal not allowed in output_path: {output_path}")


def _write_mp3(output_path: str, mp3_data: bytes) -> str:
    """Write MP3 data to disk. Returns the filename (basename only)."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(mp3_data)
    return os.path.basename(output_path)


async def synthesize_to_file(
    text: str,
    voice_id: str,
    output_path: str,
    *,
    speaking_rate: float = 1.0,
    synthesize: SynthesizeFn | None = None,
) -> str:
    """Synthesize text to an MP3 file.

    Returns the filename (not full path) for URL construction.
    Pass a custom ``synthesize`` callable for testing.
    """
    _validate_output_path(output_path)

    if synthesize is None:
        synthesize = partial(inworld_tts, speaking_rate=speaking_rate)

    mp3_data = await synthesize(text, voice_id)
    mp3_data = _reencode_mp3(mp3_data)

    filename = _write_mp3(output_path, mp3_data)
    logger.info("Audio rendered: %s (%d bytes)", filename, len(mp3_data))

    return filename


def _generate_mp3_silence(seconds: float) -> bytes:
    """Generate silent MP3 audio of the specified duration using ffmpeg."""
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=44100:cl=mono",
                "-t",
                f"{seconds:.3f}",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "128k",
                tmp_path,
            ],
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0:
            logger.warning("ffmpeg silence generation failed: %s", result.stderr[-200:])
            return b""
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)


async def synthesize_with_pauses(
    text: str,
    voice_id: str,
    output_path: str,
    *,
    speaking_rate: float = 1.0,
    session: aiohttp.ClientSession | None = None,
) -> str:
    """Synthesize text to MP3 with pause/silence insertion between sentences.

    Replicates the live agent's pause behavior for pre-rendered audio:
    - Splits on pause markers (..., \u2026, \u2014, \u2013) and inserts silence
    - Inserts silence after sentence endings (.!?)
    - Inserts longer silence at paragraph breaks (\\n\\n)
    - Passes speaking_rate to the TTS API

    Returns the filename (not full path) for URL construction.
    """
    _validate_output_path(output_path)

    chunks = chunk_text_with_pauses(text)
    mp3_parts: list[bytes] = []
    silence_cache: dict[float, bytes] = {}

    for chunk in chunks:
        if chunk.text:
            audio = await inworld_tts(
                chunk.text,
                voice_id,
                speaking_rate=speaking_rate,
                session=session,
            )
            mp3_parts.append(audio)
        elif chunk.silence:
            if chunk.silence not in silence_cache:
                silence_cache[chunk.silence] = _generate_mp3_silence(chunk.silence)
            silence = silence_cache[chunk.silence]
            if silence:
                mp3_parts.append(silence)

    if not mp3_parts:
        raise RuntimeError("No audio produced from text chunks")

    combined = b"".join(mp3_parts)
    combined = _reencode_mp3(combined)

    filename = _write_mp3(output_path, combined)
    logger.info(
        "Audio rendered with pauses: %s (%d bytes, %d chunks)",
        filename,
        len(combined),
        len(chunks),
    )
    return filename
