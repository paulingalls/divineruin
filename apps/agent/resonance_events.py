"""Client push path for the M3.1 Resonance system (story-003).

publish_resonance_changed reads the session's ResonanceTrack and emits a
RESONANCE_CHANGED event ({state, current, max}) over the game_events data channel.
This is the reusable push: M3.1's rest reset calls it, and M3.3 cast_spell reuses
it after generation. The HUD renders only the qualitative ``state`` (story-004) —
the player never sees the number (spec game_mechanics_magic.md:98).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from event_types import RESONANCE_CHANGED
from game_events import publish_game_event

if TYPE_CHECKING:
    from livekit import rtc

    from event_bus import EventBus
    from session_data import SessionData

# Resonance has no hard cap (spec game_mechanics_magic.md:132-134); it climbs
# indefinitely. This is a display ceiling for the payload — the overreach floor,
# where the qualitative state tops out — not a real bound. The HUD shows state
# only, so it is informational for any future numeric consumer.
RESONANCE_DISPLAY_MAX = 9


async def publish_resonance_changed(
    session: SessionData,
    *,
    room: rtc.Room | None = None,
    event_bus: EventBus | None = None,
) -> None:
    """Push the session's current Resonance to the client as a RESONANCE_CHANGED event.

    Defaults room/event_bus to the session's own — callers may override (e.g. tests).
    The state is derived from session.resonance, never stored.
    """
    payload = {
        "state": session.resonance.state,
        "current": session.resonance.current,
        "max": RESONANCE_DISPLAY_MAX,
    }
    await publish_game_event(
        room or session.room,
        RESONANCE_CHANGED,
        payload,
        event_bus or session.event_bus,
    )
