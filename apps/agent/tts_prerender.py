"""TTS audio pre-rendering for async activity narrations."""

import logging
import os
import wave

from livekit.plugins.inworld import TTS

logger = logging.getLogger("divineruin.tts_prerender")

DEFAULT_SAMPLE_RATE = 24000
DEFAULT_CHANNELS = 1
DEFAULT_SAMPLE_WIDTH = 2  # 16-bit PCM


async def synthesize_to_file(
    text: str,
    voice_id: str,
    output_path: str,
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> str:
    """Synthesize text to a WAV file using Inworld TTS.

    Returns the filename (not full path) for URL construction.
    """
    tts = TTS(voice=voice_id)

    # Collect PCM frames from the synthesizer
    pcm_data = bytearray()
    stream = tts.synthesize(text)
    async for event in stream:
        frame = event.frame
        if frame and frame.data:
            pcm_data.extend(frame.data)
    await stream.aclose()

    # Write WAV file
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with wave.open(output_path, "wb") as wf:
        wf.setnchannels(DEFAULT_CHANNELS)
        wf.setsampwidth(DEFAULT_SAMPLE_WIDTH)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(pcm_data))

    filename = os.path.basename(output_path)
    file_size = os.path.getsize(output_path)
    duration_seconds = len(pcm_data) / (sample_rate * DEFAULT_CHANNELS * DEFAULT_SAMPLE_WIDTH)
    logger.info(
        "Audio rendered: %s (%.1fs, %d bytes)",
        filename,
        duration_seconds,
        file_size,
    )

    return filename
