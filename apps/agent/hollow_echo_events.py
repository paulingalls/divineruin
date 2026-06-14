"""Client push path for the M3.2 Hollow Echo (story-004).

publish_hollow_echo emits a HOLLOW_ECHO_RESULT event carrying ONLY the qualitative ``band``
over the game_events data channel — the dramatic-dice overlay (story-005) maps the band to a
label/colour, and the raw d20 roll stays server-side (the same no-number discipline as
resonance_events). cast_spell calls this after a cast lands the caster at Overreach.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from event_types import HOLLOW_ECHO_RESULT
from game_events import publish_game_event

if TYPE_CHECKING:
    from livekit import rtc

    from event_bus import EventBus
    from hollow_echo import HollowEchoResult
    from session_data import SessionData


async def publish_hollow_echo(
    session: SessionData,
    result: HollowEchoResult,
    *,
    room: rtc.Room | None = None,
    event_bus: EventBus | None = None,
) -> None:
    """Push a Hollow Echo band to the client as a HOLLOW_ECHO_RESULT event.

    Defaults room/event_bus to the session's own — callers may override (e.g. tests). Only the
    band crosses to the client; the effective roll + descriptor stay in the DM's tool packet.
    """
    payload = {"band": result.band}
    await publish_game_event(
        room or session.room,
        HOLLOW_ECHO_RESULT,
        payload,
        event_bus or session.event_bus,
    )
