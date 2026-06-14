"""Vaelti Hyper-awareness 1-round advance warning (story-009).

Spec game_mechanics_magic.md:246-252: a Vaelti senses a Hollow Echo a beat before it
manifests. Emitted (bus-only -- DM narration, not client UI) when a Vaelti's cast reaches
Overreach; consumed by bg_event_handlers, which queues the warning speech onto the
background process's narration path so the DM voices the pre-sense before the echo lands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from event_bus import GameEvent
from event_types import VAELTI_ECHO_WARNING

if TYPE_CHECKING:
    from event_bus import EventBus
    from session_data import SessionData

# The DM-speech instruction the background process voices a beat before the echo lands.
WARNING_INSTRUCTION = (
    "The Vaelti's sharp senses catch the ripple before the wave — a heartbeat of warning "
    "that something is coming through the Veil. Voice it urgently in one short sentence so "
    "the party can brace. Do not name the effect yet."
)


def publish_vaelti_echo_warning(session: SessionData, *, event_bus: EventBus | None = None) -> None:
    """Emit the Vaelti advance-warning to the event bus (narration-only, server-internal)."""
    (event_bus or session.event_bus).publish(GameEvent(event_type=VAELTI_ECHO_WARNING, payload={}))
