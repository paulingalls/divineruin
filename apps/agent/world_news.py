"""Generate world news summaries from recent events for catch-up feed."""

import json
import logging
import os
import uuid

import db
from llm_config import AUDIO_DIR, MODEL, audio_url_for, extract_llm_text
from llm_config import client as _client
from tts_prerender import synthesize_to_file

logger = logging.getLogger("divineruin.world_news")


async def generate_world_news(player_id: str) -> dict | None:
    """Query recent world events and generate a news summary with audio.

    Returns a dict with {id, title, summary, narration_text, audio_url} or None
    if no significant events occurred.
    """
    pool = await db.get_pool()

    # Get the player's last check-in time (last collected activity or 24h ago)
    last_check = await pool.fetchval(
        """
        SELECT COALESCE(
            MAX(updated_at),
            NOW() - INTERVAL '24 hours'
        ) FROM async_activities
        WHERE player_id = $1 AND data->>'status' = 'collected'
        """,
        player_id,
    )

    # Get recent world events since last check-in
    rows = await pool.fetch(
        """
        SELECT data FROM world_events_log
        WHERE timestamp > $1
        ORDER BY timestamp DESC
        LIMIT 10
        """,
        last_check,
    )

    if not rows:
        return None

    events = [json.loads(row["data"]) for row in rows]
    event_summaries = []
    for ev in events:
        ev_type = ev.get("type", "event")
        desc = ev.get("description", ev.get("summary", str(ev)))
        event_summaries.append(f"- {ev_type}: {desc}")

    if not event_summaries:
        return None

    events_text = "\n".join(event_summaries[:5])

    system_msg = (
        "You write brief world news summaries for a dark fantasy RPG. "
        "30-60 words. Present tense. Atmospheric, hinting at consequences. "
        "Write for the ear."
    )

    response = await _client.messages.create(
        model=MODEL,
        max_tokens=150,
        system=system_msg,
        messages=[
            {
                "role": "user",
                "content": f"Summarize these recent world events into a single news update:\n{events_text}",
            }
        ],
    )

    narration_text = extract_llm_text(response)
    logger.info(
        "World news generated: %d input tokens, %d output tokens",
        response.usage.input_tokens,
        response.usage.output_tokens,
    )

    # Generate title from first few words
    title_words = narration_text.split()[:5]
    title = " ".join(title_words).rstrip(".,;:") + "..."

    # Synthesize audio
    news_id = f"news_{uuid.uuid4().hex[:12]}"
    audio_filename = f"{news_id}.mp3"
    audio_path = os.path.join(AUDIO_DIR, audio_filename)
    try:
        await synthesize_to_file(narration_text, "narrator_default", audio_path)
        audio_url = audio_url_for(audio_filename)
    except Exception:
        logger.warning("Failed to synthesize world news audio")
        audio_url = None

    # Store in database
    news_data = {
        "title": title,
        "summary": narration_text[:200],
        "narration_text": narration_text,
        "audio_url": audio_url,
        "event_count": len(event_summaries),
        "created_at": None,  # Will be set by DB default
    }

    await pool.execute(
        "INSERT INTO world_news_items (id, player_id, data) VALUES ($1, $2, $3::jsonb)",
        news_id,
        player_id,
        json.dumps(news_data),
    )

    return {"id": news_id, **news_data}
