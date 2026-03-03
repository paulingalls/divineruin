from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from livekit import rtc

from event_bus import EventBus

MAX_RECENT_EVENTS = 20


@dataclass
class SessionData:
    player_id: str
    location_id: str
    room: rtc.Room | None = field(default=None, repr=False)
    event_bus: EventBus = field(default_factory=EventBus)
    world_time: str = "evening"
    in_combat: bool = False
    combat_id: str | None = None
    last_player_speech_time: float = 0.0
    recent_events: deque[str] = field(default_factory=lambda: deque(maxlen=MAX_RECENT_EVENTS))

    def record_event(self, description: str) -> None:
        self.recent_events.append(description)
