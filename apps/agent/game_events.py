"""Data channel event publishing for client-side effects."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from livekit import rtc

if TYPE_CHECKING:
    from event_bus import EventBus

logger = logging.getLogger("divineruin.events")


async def publish_game_event(
    room: rtc.Room | None,
    event_type: str,
    payload: dict,
    event_bus: EventBus | None = None,
) -> None:
    """Publish a game event over the LiveKit data channel and optionally
    to the internal event bus.

    Silently skips the data channel if room is None (e.g. during tests).
    Silently skips the event bus if event_bus is None (backward compat).
    """
    if room is not None:
        data = json.dumps({"type": event_type, **payload}).encode("utf-8")
        await room.local_participant.publish_data(
            data, reliable=True, topic="game_events"
        )
        logger.debug("Published %s event to data channel", event_type)

    if event_bus is not None:
        from event_bus import GameEvent

        await event_bus.publish(GameEvent(event_type=event_type, payload=payload))
        logger.debug("Published %s event to event bus", event_type)
