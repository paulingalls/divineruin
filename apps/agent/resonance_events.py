"""Client push path for the M3.1 Resonance system (story-003).

publish_resonance_changed reads the session's ResonanceTrack and emits a
RESONANCE_CHANGED event carrying ONLY the qualitative ``state`` over the
game_events data channel. This is the reusable push: M3.1's rest reset calls it,
and M3.3 cast_spell reuses it after generation. The player never sees the raw
Resonance number (no-number spec game_mechanics_magic.md:98) — the number lives in
the DB and in-session, but never crosses to the client (story-004 M4).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from event_types import RESONANCE_CHANGED
from game_events import publish_game_event

if TYPE_CHECKING:
    from livekit import rtc

    from event_bus import EventBus
    from session_data import SessionData


async def publish_resonance_changed(
    session: SessionData,
    *,
    room: rtc.Room | None = None,
    event_bus: EventBus | None = None,
) -> None:
    """Push the session's current Resonance state to the client as a RESONANCE_CHANGED event.

    Defaults room/event_bus to the session's own — callers may override (e.g. tests).
    The state is derived from session.resonance, never stored; the raw number is never
    sent (no-number spec magic.md:98).
    """
    payload = {"state": session.resonance.state}
    await publish_game_event(
        room or session.room,
        RESONANCE_CHANGED,
        payload,
        event_bus or session.event_bus,
    )
