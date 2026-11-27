"""Transactional spell result and post-commit events."""

import inspect
from dataclasses import dataclass, field

from caster_state import ConcentrationState


@dataclass(frozen=True)
class CastResult:
    """The outcome of resolving one cast, returned by ``_resolve_cast`` for the caller to commit.

    ``_resolve_cast`` is in-memory-PURE: it persists via the passed ``conn`` but never mutates the
    session's resonance/concentration SSOT, so a rolled-back caller tx leaves the session pristine.
    The caller syncs these post-commit from this result and then flushes ``events`` (deferred so a
    rollback leaks no client event).

    ``new_resonance`` is the total after generation, or ``None`` when nothing was generated.
    ``resonance_updates`` holds final recipient totals after healing. ``concentration_update``
    is the new record, or None when the cast leaves concentration alone.
    """

    packet: dict
    new_resonance: int | None
    concentration_update: ConcentrationState | None
    generated: int
    events: list
    unbound_veil_mastery_spent: bool = False
    terrain: str | None = None
    first_stay: bool = False
    resonance_updates: dict[str, int] = field(default_factory=dict)

    async def flush_events(self) -> None:
        """Emit the deferred client events in order. Call ONLY after the caller's tx commits.

        Each entry is a zero-arg callable; sync ones (the bus-only Vaelti warning) return None,
        async ones (resonance/echo publishes) return a coroutine that is awaited."""
        for emit in self.events:
            result = emit()
            if inspect.isawaitable(result):
                await result
