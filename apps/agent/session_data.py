from __future__ import annotations

import uuid
from collections import deque
from dataclasses import asdict, dataclass, field

from livekit import rtc

from event_bus import EventBus

MAX_RECENT_EVENTS = 20
MAX_COMPANION_MEMORIES = 20


@dataclass
class CompanionState:
    id: str
    name: str
    is_present: bool = True
    is_conscious: bool = True
    emotional_state: str = "steady"
    relationship_tier: int = 1
    session_memories: list[str] = field(default_factory=list)
    last_speech_time: float = 0.0


@dataclass
class CombatParticipant:
    id: str
    name: str
    type: str  # "player", "enemy", "companion"
    initiative: int
    hp_current: int
    hp_max: int
    ac: int
    attributes: dict = field(default_factory=lambda: {"strength": 10, "dexterity": 10})
    level: int = 1
    is_fallen: bool = False
    death_save_successes: int = 0
    death_save_failures: int = 0
    action_pool: list[dict] = field(default_factory=list)
    xp_value: int = 0


@dataclass
class CombatState:
    combat_id: str
    participants: list[CombatParticipant]
    initiative_order: list[str]  # participant IDs in initiative order
    round_number: int = 1
    current_turn_index: int = 0
    location_id: str = ""

    def get_participant(self, participant_id: str) -> CombatParticipant | None:
        for p in self.participants:
            if p.id == participant_id:
                return p
        return None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CreationState:
    phase: str = "prologue"  # prologue | awakening | calling | devotion | identity | complete
    race: str | None = None
    class_choice: str | None = None
    deity: str | None = None
    name: str | None = None
    backstory: str | None = None


@dataclass
class SessionData:
    player_id: str
    location_id: str
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    room: rtc.Room | None = field(default=None, repr=False)
    event_bus: EventBus = field(default_factory=EventBus)
    world_time: str = "evening"
    combat_state: CombatState | None = None
    last_player_speech_time: float = 0.0
    last_agent_speech_end: float = 0.0
    recent_events: deque[str] = field(default_factory=lambda: deque(maxlen=MAX_RECENT_EVENTS))
    attempted_discoveries: set[str] = field(default_factory=set)
    companion: CompanionState | None = None
    corruption_level: int = 0
    patron_id: str = "none"
    creation_state: CreationState | None = None

    # Cached data for hot context (updated by background process, read by voice loop)
    cached_location_name: str = ""
    cached_npc_names: list[str] = field(default_factory=list)
    cached_quest_summaries: list[str] = field(default_factory=list)

    # Session metrics tracking
    session_xp_earned: int = 0
    session_items_found: list[str] = field(default_factory=list)
    session_quests_progressed: list[str] = field(default_factory=list)
    session_locations_visited: list[str] = field(default_factory=list)
    ending_requested: bool = False
    player_disconnected: bool = False
    disconnect_time: float = 0.0

    @property
    def in_creation(self) -> bool:
        return self.creation_state is not None and self.creation_state.phase != "complete"

    @property
    def in_combat(self) -> bool:
        return self.combat_state is not None

    @property
    def has_companion(self) -> bool:
        return self.companion is not None and self.companion.is_present

    @property
    def companion_can_act(self) -> bool:
        return self.companion is not None and self.companion.is_present and self.companion.is_conscious

    def record_event(self, description: str) -> None:
        self.recent_events.append(description)

    def record_companion_memory(self, memory: str) -> None:
        if self.companion is None:
            return
        self.companion.session_memories.append(memory)
        if len(self.companion.session_memories) > MAX_COMPANION_MEMORIES:
            self.companion.session_memories = self.companion.session_memories[-MAX_COMPANION_MEMORIES:]
