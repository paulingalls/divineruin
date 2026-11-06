"""Transactional spell result and post-commit events."""

import inspect
from dataclasses import dataclass

# Sentinel for CastResult.concentration_spell_id: a non-concentration cast never touches
# concentration, which must be distinguishable from "end concentration" (None is a valid
# concentration_spell_id). _UNCHANGED means "this cast did not touch concentration".
_UNCHANGED = object()


@dataclass(frozen=True)
class CastResult:
    """The outcome of resolving one cast, returned by ``_resolve_cast`` for the caller to commit.

    ``_resolve_cast`` is in-memory-PURE: it persists via the passed ``conn`` but never mutates the
    session's resonance/concentration SSOT, so a rolled-back caller tx leaves the session pristine.
    The caller syncs these post-commit from this result and then flushes ``events`` (deferred so a
    rollback leaks no client event).

    ``new_resonance`` is the value persisted this cast, or ``None`` when nothing was generated
    (no resonance write — a cantrip or a floored-to-0 reduction). ``concentration_spell_id`` is the
    started spell id, or the ``_UNCHANGED`` sentinel when the cast never touched concentration.
    """

    packet: dict
    new_resonance: int | None
    concentration_spell_id: object
    generated: int
    events: list

    async def flush_events(self) -> None:
        """Emit the deferred client events in order. Call ONLY after the caller's tx commits.

        Each entry is a zero-arg callable; sync ones (the bus-only Vaelti warning) return None,
        async ones (resonance/echo publishes) return a coroutine that is awaited."""
        for emit in self.events:
            result = emit()
            if inspect.isawaitable(result):
                await result
