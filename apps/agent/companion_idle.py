"""Generate and serve companion idle audio clips from a pre-rendered pool."""

import json
import logging
import os
import uuid

import db
from activity_templates import get_companion_context
from llm_config import AUDIO_DIR, MODEL, audio_url_for
from llm_config import client as _client
from tts_prerender import synthesize_to_file

logger = logging.getLogger("divineruin.companion_idle")


async def generate_idle_pool(companion_id: str, count: int = 5) -> list[dict]:
    """Batch generate idle chatter lines with TTS audio.

    Returns list of {id, text, audio_url} dicts.
    """
    system_msg = (
        "You write short idle chatter lines for a fantasy RPG companion character. "
        "Each line is 10-25 words. Atmospheric, in-character, present tense. "
        "Mix observations, small actions, and quiet remarks. No dialogue tags."
    )

    response = await _client.messages.create(
        model=MODEL,
        max_tokens=300,
        system=system_msg,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Write exactly {count} short idle chatter lines for companion '{companion_id}'. "
                    "One line per entry, no numbering."
                ),
            }
        ],
    )

    text = response.content[0].text
    lines = [line.strip() for line in text.strip().split("\n") if line.strip()]
    lines = lines[:count]

    logger.info(
        "Idle pool generated: %d lines, %d input tokens, %d output tokens",
        len(lines),
        response.usage.input_tokens,
        response.usage.output_tokens,
    )

    results = []
    for line_text in lines:
        clip_id = f"idle_{uuid.uuid4().hex[:12]}"
        audio_filename = f"{clip_id}.mp3"
        audio_path = os.path.join(AUDIO_DIR, audio_filename)

        try:
            voice_id = get_companion_context(companion_id)["voice_id"]
            await synthesize_to_file(line_text, voice_id, audio_path)
            audio_url = audio_url_for(audio_filename)
        except Exception:
            logger.warning("Failed to synthesize idle clip %s", clip_id)
            audio_url = None

        results.append(
            {
                "id": clip_id,
                "text": line_text,
                "audio_url": audio_url,
                "companion_id": companion_id,
                "heard": False,
            }
        )

    # Store clips in DB for retrieval
    pool = await db.get_pool()
    for clip in results:
        await pool.execute(
            """
            INSERT INTO async_activities (id, player_id, data)
            VALUES ($1, $2, $3::jsonb)
            """,
            clip["id"],
            "system",  # system-owned clips
            json.dumps(
                {
                    "type": "idle_clip",
                    "companion_id": companion_id,
                    "text": clip["text"],
                    "audio_url": clip["audio_url"],
                    "heard": False,
                }
            ),
        )

    return results


async def get_idle_clip(companion_id: str, player_id: str) -> dict | None:
    """Return an unheard idle clip for this companion/player combo.

    Falls back to text-only if no audio clips exist.
    """
    pool = await db.get_pool()

    # Look for an unheard clip
    row = await pool.fetchrow(
        """
        SELECT id, data FROM async_activities
        WHERE data->>'type' = 'idle_clip'
          AND data->>'companion_id' = $1
          AND (data->>'heard')::boolean = false
        ORDER BY random()
        LIMIT 1
        """,
        companion_id,
    )

    if row is None:
        return None

    clip_data = json.loads(row["data"])

    # Mark as heard
    await pool.execute(
        "UPDATE async_activities SET data = jsonb_set(data, '{heard}', 'true'::jsonb) WHERE id = $1",
        row["id"],
    )

    return {
        "id": row["id"],
        "text": clip_data.get("text", ""),
        "audio_url": clip_data.get("audio_url"),
        "companion_id": companion_id,
    }
