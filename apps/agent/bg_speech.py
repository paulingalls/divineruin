"""Speech types and constants shared by background process modules."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from time import time

COMPANION_IDLE_SECS = 45.0


class SpeechPriority(enum.IntEnum):
    ROUTINE = 0
    IMPORTANT = 1
    CRITICAL = 2


@dataclass(order=True)
class PendingSpeech:
    priority: SpeechPriority
    instructions: str = field(compare=False)
    created: float = field(default_factory=time, compare=False)
    stinger_sound: str | None = field(default=None, compare=False)
