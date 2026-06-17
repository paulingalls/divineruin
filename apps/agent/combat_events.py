"""Deferred event buffer + in-tx scratch snapshot for transactional combat resolution (story-005).

resolve_phase wraps every per-phase DB write in one transaction. Two kinds of side-effect escape
that atomicity and must be made rollback-safe:

  - Client events (DICE_ROLL, sounds, ITEM_DURABILITY_HIT, COMBAT_ENDED) can't be un-sent, so
    EventSink BUFFERS them during the tx and flush()es only after commit. On rollback the sink is
    dropped unflushed (its stack frame unwinds), so nothing reaches the client (concern 03f2907d9c93).
  - In-loop session scratch (weapon-durability flags, companion KO) is read IN-tx by end_combat's
    durability check, so it can't be deferred — _CombatScratchSnapshot captures it before the tx and
    restore()s it if the tx raises.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from game_events import publish_game_event

if TYPE_CHECKING:
    from livekit import rtc

    from event_bus import EventBus


@dataclass
class BufferedEvent:
    """One captured publish_game_event call, replayed verbatim by EventSink.flush."""

    room: "rtc.Room | None"
    event_type: str
    payload: dict
    event_bus: "EventBus | None"


@dataclass
class EventSink:
    """Captures publish_game_event calls during a transaction; flush() replays them post-commit.

    ``emit`` mirrors publish_game_event's signature so call sites swap mechanically. ``captured``
    is a plain list so tests can assert exactly what was (and wasn't) published."""

    captured: list[BufferedEvent] = field(default_factory=list)

    async def emit(
        self,
        room: "rtc.Room | None",
        event_type: str,
        payload: dict,
        *,
        event_bus: "EventBus | None" = None,
    ) -> None:
        """Same signature as publish_game_event — buffer the event instead of publishing it."""
        self.captured.append(BufferedEvent(room, event_type, payload, event_bus))

    async def flush(self) -> None:
        """Publish every buffered event in order, then clear. Call ONLY after the tx commits."""
        for ev in self.captured:
            await publish_game_event(ev.room, ev.event_type, ev.payload, event_bus=ev.event_bus)
        self.captured.clear()


@dataclass
class _CombatScratchSnapshot:
    """Pre-transaction snapshot of resolve_phase's in-loop session scratch, restored on rollback.

    weapon_used_this_encounter is read IN-tx by end_combat's durability check, so the loop must set
    it live (not defer it); restore() reverts it — and the companion KO — only when the tx fails.
    session_memories is captured by CONTENTS (a shallow copy), not length: record_companion_memory
    caps the list by dropping index 0, so a length-truncate restore would lose the oldest pre-phase
    memory once the list is at MAX_COMPANION_MEMORIES."""

    weapon_used_this_encounter: bool
    weapon_crit_vs_heavy: bool
    companion_is_conscious: bool | None
    companion_memories: list[str] | None

    @classmethod
    def capture(cls, session) -> "_CombatScratchSnapshot":
        companion = session.companion
        return cls(
            weapon_used_this_encounter=session.weapon_used_this_encounter,
            weapon_crit_vs_heavy=session.weapon_crit_vs_heavy,
            companion_is_conscious=companion.is_conscious if companion is not None else None,
            companion_memories=list(companion.session_memories) if companion is not None else None,
        )

    def restore(self, session) -> None:
        session.weapon_used_this_encounter = self.weapon_used_this_encounter
        session.weapon_crit_vs_heavy = self.weapon_crit_vs_heavy
        companion = session.companion
        if companion is not None and self.companion_memories is not None:
            companion.is_conscious = self.companion_is_conscious
            companion.session_memories = list(self.companion_memories)
