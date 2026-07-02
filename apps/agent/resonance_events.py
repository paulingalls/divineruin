"""Client push path for the M3.1 Resonance system (story-003).

publish_resonance_changed reads a ResonanceTrack and emits a RESONANCE_CHANGED event
carrying the qualitative ``state`` plus a ``caster_id`` discriminator over the
game_events data channel. This is the reusable push: M3.1's rest reset calls it,
and M3.3 cast_spell reuses it after generation. The player never sees the raw
Resonance number (no-number spec game_mechanics_magic.md:98) — the number lives in
the DB and in-session, but never crosses to the client (story-004 M4).

``resonance_track`` / ``caster_id`` (M14 story-004) let the multi-player phase loop push
EACH member's own state under its own id; both default to the session primary
(session.resonance / session.player_id) so single-player pushes are byte-identical. The
mobile client filters on caster_id, updating its single global HUD tracker only for the
local player's pushes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from event_types import RESONANCE_CHANGED
from game_events import publish_game_event

if TYPE_CHECKING:
    from livekit import rtc

    from caster_state import ResonanceTrack
    from event_bus import EventBus
    from session_data import SessionData


async def publish_resonance_changed(
    session: SessionData,
    *,
    resonance_track: ResonanceTrack | None = None,
    caster_id: str | None = None,
    room: rtc.Room | None = None,
    event_bus: EventBus | None = None,
) -> None:
    """Push a member's current Resonance state to the client as a RESONANCE_CHANGED event.

    ``resonance_track`` / ``caster_id`` default to the session primary (session.resonance /
    session.player_id), so a single-player push is byte-identical. room/event_bus default to the
    session's own — callers may override (e.g. tests). The state is derived from the track, never
    stored; the raw number is never sent (no-number spec magic.md:98).
    """
    track = resonance_track if resonance_track is not None else session.resonance
    payload = {"state": track.state, "caster_id": caster_id if caster_id is not None else session.player_id}
    await publish_game_event(
        room or session.room,
        RESONANCE_CHANGED,
        payload,
        event_bus or session.event_bus,
    )
