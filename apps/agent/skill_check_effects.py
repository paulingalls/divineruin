"""Effects released by the skill check's transaction owner after commit."""

from dataclasses import dataclass, field

from combat_state import CombatState


@dataclass
class SkillCheckEffects:
    combat_state: CombatState | None = None
    events: list[tuple[str, dict]] = field(default_factory=list)
    recent_event: str | None = None

    async def flush(self, session, *, publish):
        if self.combat_state is not None:
            session.combat_state = self.combat_state
        if self.recent_event is not None:
            session.record_event(self.recent_event)
        for kind, payload in self.events:
            await publish(session.room, kind, payload, event_bus=session.event_bus)
