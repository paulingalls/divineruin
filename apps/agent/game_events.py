"""Data channel event publishing for client-side effects."""

import json
import logging

from livekit import rtc

logger = logging.getLogger("divineruin.events")


async def publish_game_event(
    room: rtc.Room | None,
    event_type: str,
    payload: dict,
) -> None:
    """Publish a game event over the LiveKit data channel.

    Silently returns if room is None (e.g. during tests).
    """
    if room is None:
        return

    data = json.dumps({"type": event_type, **payload}).encode("utf-8")
    await room.local_participant.publish_data(
        data, reliable=True, topic="game_events"
    )
    logger.debug("Published %s event", event_type)
