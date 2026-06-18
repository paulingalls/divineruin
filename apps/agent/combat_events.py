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

from collections import deque
from contextlib import asynccontextmanager
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


async def emit_or_publish(
    sink: "EventSink | None",
    room: "rtc.Room | None",
    event_type: str,
    payload: dict,
    *,
    event_bus: "EventBus | None" = None,
) -> None:
    """Buffer the event in ``sink`` when one is active (the in-transaction combat path), else
    publish it immediately. Lets the combat publish helpers serve both the buffered phase loop
    and their existing direct (non-tx) callers with one call site."""
    if sink is not None:
        await sink.emit(room, event_type, payload, event_bus=event_bus)
    else:
        await publish_game_event(room, event_type, payload, event_bus=event_bus)


@dataclass
class _CombatScratchSnapshot:
    """Pre-transaction snapshot of resolve_phase's in-loop session scratch, restored on rollback.

    weapon_used_this_encounter is read IN-tx by end_combat's durability check, so the loop must set
    it live (not defer it); restore() reverts it — and the companion KO, plus the per-attack
    recent_events the loop records — only when the tx fails. Lists are captured by CONTENTS (a
    shallow copy), not length: record_companion_memory / record_event cap their backing store by
    dropping the oldest entry, so a length-truncate restore would lose the oldest pre-phase entry
    once at the cap.

    concentration_spell_id is reverted too (story-007): an in-loop ABILITY cast starts a new
    concentration, and break_concentration_on_damage clears it, both IN memory mid-tx — a rolled-back
    phase must restore the pre-phase concentration so it can't diverge from the rolled-back DB row."""

    weapon_used_this_encounter: bool
    weapon_crit_vs_heavy: bool
    recent_events: list[str]
    companion_is_conscious: bool | None
    companion_memories: list[str] | None
    concentration_spell_id: str | None

    @classmethod
    def capture(cls, session) -> "_CombatScratchSnapshot":
        companion = session.companion
        return cls(
            weapon_used_this_encounter=session.weapon_used_this_encounter,
            weapon_crit_vs_heavy=session.weapon_crit_vs_heavy,
            recent_events=list(session.recent_events),
            companion_is_conscious=companion.is_conscious if companion is not None else None,
            companion_memories=list(companion.session_memories) if companion is not None else None,
            concentration_spell_id=session.concentration.spell_id,
        )

    def restore(self, session) -> None:
        session.weapon_used_this_encounter = self.weapon_used_this_encounter
        session.weapon_crit_vs_heavy = self.weapon_crit_vs_heavy
        session.recent_events = deque(self.recent_events, maxlen=session.recent_events.maxlen)
        session.concentration.spell_id = self.concentration_spell_id
        companion = session.companion
        if companion is not None and self.companion_memories is not None:
            companion.is_conscious = self.companion_is_conscious
            companion.session_memories = list(self.companion_memories)


@asynccontextmanager
async def scratch_guard(session):
    """Capture resolve_phase's in-loop session scratch on enter, and restore it if the wrapped
    block raises. Enter this guard OUTSIDE db.transaction() so that on a mid-phase failure the tx
    rolls back first, then the snapshot reverts the in-memory scratch (weapon flags, companion KO,
    recent_events) — no in-memory state sticks through a rolled-back phase (story-005, AC3)."""
    snapshot = _CombatScratchSnapshot.capture(session)
    try:
        yield
    except BaseException:
        snapshot.restore(session)
        raise
