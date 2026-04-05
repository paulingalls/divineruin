"""LLM-generated session summary with structured output."""

from __future__ import annotations

import asyncio
import json
import logging
import time

import db_queries
from asset_utils import slug_asset_url
from llm_config import MODEL as _MODEL
from llm_config import client as _client
from llm_config import extract_llm_text
from session_data import SessionData

logger = logging.getLogger("divineruin.summary")

_SUMMARY_PROMPT = """\
You are summarizing a tabletop RPG session for the Dungeon Master to use as context \
in the next session. The player hears a recap read aloud — write for the ear.

Given the session transcript and metrics below, produce a JSON object with these fields:
- "summary": 2-3 sentence narrative recap in second person, past tense. For audio playback.
- "key_events": list of 3-5 important things that happened (short strings).
- "decisions": list of player choices that could have consequences (short strings). Empty list if none.
- "next_hooks": 1-2 unresolved threads or teases for next session (short strings).

Respond with ONLY the JSON object, no markdown fences, no explanation.

Session metrics:
- XP earned: {xp_earned}
- Items found: {items_found}
- Quests progressed: {quests_progressed}
- Locations visited: {locations_visited}
- Duration: {duration_minutes} minutes

Recent transcript (last ~100 lines):
{transcript_tail}
"""


async def generate_session_summary(
    session_data: SessionData,
    transcript_path: str | None,
    session_start_time: float | None = None,
) -> dict:
    """Generate a rich session summary using LLM + hard metrics.

    Falls back to a naive summary if the LLM call fails.
    """
    elapsed = time.time() - session_start_time if session_start_time else 0.0
    duration_minutes = round(elapsed / 60, 1)

    metrics = {
        "xp_earned": session_data.session_xp_earned,
        "items_found": session_data.session_items_found,
        "quests_progressed": session_data.session_quests_progressed,
        "locations_visited": session_data.session_locations_visited,
        "duration": round(elapsed),
    }

    recent = list(session_data.recent_events)

    # Read transcript tail
    transcript_tail = ""
    if transcript_path:
        try:
            with open(transcript_path, encoding="utf-8") as f:
                lines = f.readlines()
            transcript_tail = "".join(lines[-100:])
        except Exception:
            logger.debug("Could not read transcript at %s", transcript_path)

    if not transcript_tail:
        tail_events = recent[-10:]
        transcript_tail = "\n".join(tail_events) if tail_events else "No transcript available."

    # Run LLM summary and story moments fetch concurrently
    async def _fetch_story_moments() -> list:
        try:
            return await db_queries.get_session_story_moments(session_data.session_id)
        except Exception:
            logger.debug("Could not fetch story moments for session %s", session_data.session_id)
            return []

    llm_result, story_moments_raw = await asyncio.gather(
        _call_llm_summary(
            xp_earned=metrics["xp_earned"],
            items_found=", ".join(metrics["items_found"]) or "none",
            quests_progressed=", ".join(metrics["quests_progressed"]) or "none",
            locations_visited=", ".join(metrics["locations_visited"]) or "none",
            duration_minutes=duration_minutes,
            transcript_tail=transcript_tail,
        ),
        _fetch_story_moments(),
    )

    story_moments = [
        {
            "moment_key": m["moment_key"],
            "description": m["description"],
            "image_url": slug_asset_url(m["asset_id"]) if m.get("asset_id") else None,
        }
        for m in story_moments_raw
    ]

    if llm_result is not None:
        # Merge LLM output with hard metrics
        return {
            "summary": llm_result.get("summary", ""),
            "key_events": llm_result.get("key_events", []),
            "decisions": llm_result.get("decisions", []),
            "next_hooks": llm_result.get("next_hooks", []),
            "story_moments": story_moments,
            **metrics,
        }

    # Fallback: naive summary from recent events
    fallback_events = recent[-5:]
    summary_text = " ".join(fallback_events) if fallback_events else "A brief venture into the world."
    return {
        "summary": summary_text,
        "key_events": fallback_events,
        "decisions": [],
        "next_hooks": [],
        "story_moments": story_moments,
        **metrics,
    }


async def _call_llm_summary(
    xp_earned: int,
    items_found: str,
    quests_progressed: str,
    locations_visited: str,
    duration_minutes: float,
    transcript_tail: str,
) -> dict | None:
    """Call Claude Haiku to generate structured summary. Returns None on failure."""
    try:
        prompt = _SUMMARY_PROMPT.format(
            xp_earned=xp_earned,
            items_found=items_found,
            quests_progressed=quests_progressed,
            locations_visited=locations_visited,
            duration_minutes=duration_minutes,
            transcript_tail=transcript_tail[:4000],  # Token budget guard
        )
        response = await _client.messages.create(
            model=_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = extract_llm_text(response)
        if not text:
            logger.warning("LLM returned empty text for summary (stop_reason=%s)", response.stop_reason)
            return None

        # Strip markdown fences if the model wraps the JSON anyway
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        return json.loads(text)
    except Exception:
        logger.warning("LLM summary generation failed — using fallback", exc_info=True)
        return None
