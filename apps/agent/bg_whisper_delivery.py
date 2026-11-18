"""Recipient naming and successful-delivery bookkeeping for divine whispers."""

import logging

import db_activity_queries
import db_mutations_divine
import db_queries
from alignment_heartbeat import TRANSIENT_IO_ERRORS
from bg_speech import PendingSpeech
from sanitize import sanitize_for_prompt
from session_data import SessionData

logger = logging.getLogger("divineruin.background")


async def named_whisper(speech: PendingSpeech) -> str:
    assert speech.recipient_id is not None
    player = await db_queries.get_player(speech.recipient_id)
    if player is None or not player["name"].strip():
        raise ValueError(f"Whisper recipient has no name: {speech.recipient_id}")
    name = sanitize_for_prompt(player["name"], max_len=100)
    return (
        speech.instructions + f' This whisper is for "{name}". Say their name aloud so the table knows whose god spoke.'
    )


async def mark_whisper(speech: PendingSpeech, sd: SessionData) -> None:
    if speech.is_displeasure:
        assert speech.recipient_id is not None
        sd.displeasure_heard_by.add(speech.recipient_id)
    elif speech.stinger_sound is not None:
        assert speech.recipient_id is not None
        try:
            favor = await db_activity_queries.get_divine_favor(speech.recipient_id)
            if favor:
                await db_mutations_divine.mark_favor_whisper_level(speech.recipient_id, favor.get("level", 0))
        except TRANSIENT_IO_ERRORS:
            logger.warning("Failed to mark favor whisper level", exc_info=True)
