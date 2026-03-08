"""TTS audio pre-rendering for async activity narrations."""

import logging
import os

from livekit.plugins.inworld import TTS

logger = logging.getLogger("divineruin.tts_prerender")


async def synthesize_to_file(
    text: str,
    voice_id: str,
    output_path: str,
) -> str:
    """Synthesize text to an MP3 file using Inworld TTS.

    Returns the filename (not full path) for URL construction.
    """
    if ".." in output_path:
        raise ValueError(f"Path traversal not allowed in output_path: {output_path}")

    tts = TTS(voice=voice_id, encoding="MP3")

    # Collect MP3 frames from the synthesizer
    mp3_data = bytearray()
    stream = tts.synthesize(text)
    async for event in stream:
        frame = event.frame
        if frame and frame.data:
            mp3_data.extend(frame.data)
    await stream.aclose()

    # Write MP3 file
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(mp3_data)

    filename = os.path.basename(output_path)
    file_size = os.path.getsize(output_path)
    logger.info("Audio rendered: %s (%d bytes)", filename, file_size)

    return filename
