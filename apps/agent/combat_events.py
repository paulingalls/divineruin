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

import logging
from collections import deque
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from game_events import publish_game_event

if TYPE_CHECKING:
    from livekit import rtc

    from event_bus import EventBus

logger = logging.getLogger("divineruin.combat_events")

# Post-commit publish policy for BOTH combat-end paths (story-010, decision 788d61b73623): once the
# end transaction commits, the committed rewards are authoritative and the HUD is only a mirror. A
# mirror that fails to update must NOT strand a session whose rewards are already banked — the
# handoff _end_combat_finish returns is the only exit from CombatAgent (end_combat returns it
# directly, resolve_phase relays it), so a raise between the commit and that return would leave the
# party unable to leave combat at all. So a publish failure is logged and the teardown/handoff still
# completes. Deliberate: it trades a possibly-stale HUD (self-healing on the next push) for a
# session that can always get out.
POST_COMMIT_PUBLISH_FAILED = "%s: post-commit publish failed; the committed end stands, the HUD may lag"


@contextmanager
def isolated_publish(label: str):
    """Contain ONE post-commit publish's failure to that publish.

    A single ``try`` around a sequence of independent publishes is a hidden dependency: the first
    failure skips every push after it, so a transient error flushing the event sink silently costs
    the ward indicator, the deferred ability events and every member's Resonance push too — none of
    which re-fire, and all of which the mechanic keeps using the real values behind. Each push is
    independent of the others, so each gets its own guard and the rest still land.
    """
    try:
        yield
    except Exception:
        logger.exception(POST_COMMIT_PUBLISH_FAILED, label)


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

    The weapon-durability flags are read IN-tx by end_combat's per-member durability check, so the
    loop must set them live (not defer them); restore() reverts them — and the companion KO, plus
    the per-attack recent_events the loop records — only when the tx fails. Lists are captured by
    CONTENTS (a shallow copy), not length: record_companion_memory / record_event cap their backing
    store by dropping the oldest entry, so a length-truncate restore would lose the oldest pre-phase
    entry once at the cap.

    The weapon flags are captured PER PARTY MEMBER (M18 story-003): a swing arms the SWINGING
    member's own flags (combat_packet), so a multi-PC rollback must revert every member's flags, not
    just the primary's — mirroring the concentration snapshot below. Solo = 1 member, so this is
    byte-identical to the single-player revert.

    concentration is reverted too (story-007): an in-loop ABILITY cast starts a new concentration,
    and break_concentration_on_damage clears it, both IN memory mid-tx — a rolled-back phase must
    restore the pre-phase concentration so it can't diverge from the rolled-back DB row. Captured
    PER PARTY MEMBER (M14 story-004): the in-loop concentration sync moved to the declaring caster's
    own pool, so a multi-PC rollback must revert every member's concentration, not just the primary's
    (solo = 1 member, so this is byte-identical to the single-player revert)."""

    weapon_used: dict[str, bool]
    weapon_crit_vs_heavy: dict[str, bool]
    recent_events: list[str]
    companion_is_conscious: bool | None
    companion_memories: list[str] | None
    concentration_spell_ids: dict[str, str | None]

    @classmethod
    def capture(cls, session) -> "_CombatScratchSnapshot":
        companion = session.companion
        return cls(
            weapon_used={m.player_id: m.weapon_used for m in session.party.members},
            weapon_crit_vs_heavy={m.player_id: m.weapon_crit_vs_heavy for m in session.party.members},
            recent_events=list(session.recent_events),
            companion_is_conscious=companion.is_conscious if companion is not None else None,
            companion_memories=list(companion.session_memories) if companion is not None else None,
            concentration_spell_ids={m.player_id: m.concentration.spell_id for m in session.party.members},
        )

    def restore(self, session) -> None:
        session.recent_events = deque(self.recent_events, maxlen=session.recent_events.maxlen)
        for player_id, used in self.weapon_used.items():
            member = session.party.member(player_id)
            if member is not None:
                member.weapon_used = used
                member.weapon_crit_vs_heavy = self.weapon_crit_vs_heavy[player_id]
        for player_id, spell_id in self.concentration_spell_ids.items():
            member = session.party.member(player_id)
            if member is not None:
                member.concentration.spell_id = spell_id
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
