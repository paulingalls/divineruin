"""Async god whisper generation: LLM text + TTS audio + DB persistence."""

import logging
import os

import db_mutations
from god_whisper_data import get_god_profile
from llm_config import AUDIO_DIR, MODEL, audio_url_for, client, extract_llm_text
from push import send_push_notification
from tts_prerender import synthesize_with_pauses
from voices import get_voice_config

logger = logging.getLogger("divineruin.god_whisper_generator")


async def generate_god_whisper(
    player_id: str,
    deity_id: str,
    context: str = "",
) -> str:
    """Generate a god whisper: LLM narration + TTS audio + DB record.

    Returns the whisper ID.
    """
    profile = get_god_profile(deity_id)

    # Generate whisper text via Claude Haiku
    prompt = (
        f"{profile.personality_prompt}\n\n"
        "Generate a 2-3 sentence whisper from this god to their mortal champion. "
        "Write ONLY the god's words — no stage directions, no narration. "
        "Short, weighted sentences. Ancient perspective. "
        f"{f'Context: {context}' if context else ''}"
    )

    response = await client.messages.create(
        model=MODEL,
        max_tokens=150,
        messages=[{"role": "user", "content": prompt}],
    )
    narration_text = extract_llm_text(response)

    # Pre-render TTS
    voice_cfg = get_voice_config(profile.voice_character, profile.voice_emotion)
    audio_filename = f"whisper_{player_id}_{deity_id}_{os.urandom(4).hex()}.mp3"
    audio_path = os.path.join(AUDIO_DIR, audio_filename)
    await synthesize_with_pauses(narration_text, voice_cfg, audio_path)
    audio_url = audio_url_for(audio_filename)

    # Store in DB
    whisper_data = {
        "deity_id": deity_id,
        "narration_text": narration_text,
        "audio_url": audio_url,
        "status": "pending",
    }
    whisper_id = await db_mutations.create_god_whisper(player_id, whisper_data)

    logger.info(
        "God whisper generated: id=%s, deity=%s, player=%s",
        whisper_id,
        deity_id,
        player_id,
    )

    # Send push notification
    display_name = profile.display_name
    try:
        await send_push_notification(
            player_id,
            f"{display_name} has a message for you",
            narration_text[:100],
        )
    except Exception:
        logger.warning("Failed to send god whisper push notification")

    return whisper_id
