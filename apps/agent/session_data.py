from dataclasses import dataclass, field

from livekit import rtc


@dataclass
class SessionData:
    player_id: str
    location_id: str
    room: rtc.Room | None = field(default=None, repr=False)
