from __future__ import annotations

import uuid
from collections import deque
from dataclasses import asdict, dataclass, field

from livekit import rtc

import resonance
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
    # HYBRID relationship model (M6.4 / story-003): session_count + affinity are the authoritative
    # inputs; the named tier is DERIVED (companion_relationship.effective_tier_rank/tier_name), never
    # stored in-memory, so there is no cached copy to drift. Persisted in companion_relationships.
    session_count: int = 0
    affinity: int = 0
    session_memories: list[str] = field(default_factory=list)
    last_speech_time: float = 0.0


@dataclass
class ResonanceTrack:
    """Per-caster Resonance carried in the session (story-003, M3.1).

    Only ``current`` (the authoritative int) is stored; the stable/flickering/
    overreach STATE is always derived via resonance.get_resonance_state — single
    source of truth, no cached copy to drift (same discipline as the companion
    HYBRID tier above and the players.data persistence in db_mutations_resonance).
    Defaults to current 0 -> "stable".

    ``flickering_bonus`` (Thessyn Deep Adaptation, M3.4) shifts the band thresholds
    up; it is a per-caster constant set once from the player's race (story-006), so
    EVERY derivation of ``state`` — the packet, the HUD push (publish_resonance_changed),
    the cast path — reads the same single value and cannot diverge. Defaults to 0
    (the canonical band) for non-Thessyn casters.
    """

    current: int = 0
    flickering_bonus: int = 0

    @property
    def state(self) -> resonance.ResState:
        return resonance.get_resonance_state(self.current, flickering_bonus=self.flickering_bonus)


@dataclass
class VeilWardState:
    """Per-caster Veil Ward carried in the session (story-002, M3.2).

    A ward is a manual activate/dismiss toggle (no auto-expiry in M3.2). ``active``
    drives the cast-path halving (story-004); ``source`` is the archetype id that raised
    it, carried for narration/HUD flavor. Synced from players.data by the activation tool
    (story-003), persisted via db_mutations_veil_ward. Defaults to inactive.
    """

    active: bool = False
    source: str | None = None


@dataclass
class ConcentrationState:
    """Per-caster spell concentration carried in the session (story-002, M3.4).

    A caster sustains at most ONE concentration spell at a time; ``spell_id`` is that spell
    (None = not concentrating). The cast keystone (story-006) sets it on a concentration cast
    and ends any prior one (single-concentration enforcement), persisted via
    db_mutations_concentration. Like ResonanceTrack/VeilWardState, only the authoritative id
    is stored — ``is_active`` is always derived, no cached flag to drift. Defaults to inactive.
    """

    spell_id: str | None = None

    @property
    def is_active(self) -> bool:
        return self.spell_id is not None


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
    # Declaration enhancers this participant has been granted (M4.2, story-004). Keys:
    # extra_attack, shield_bash, cunning_action, hit_and_run, command_lesser, quick_change.
    # An enhancer EXPANDS what one declaration resolves into; it never grants a 2nd
    # declaration. Populated from players.data.flags at combat init; serializes via asdict
    # and falls back to [] for rows written before the field existed.
    enhancers: list[str] = field(default_factory=list)


@dataclass
class CombatState:
    combat_id: str
    participants: list[CombatParticipant]
    initiative_order: list[str]  # participant IDs in initiative order
    round_number: int = 1
    current_turn_index: int = 0
    location_id: str = ""

    # 4-beat phase machine (M4.1, story-001). The deterministic engine lives in
    # combat_phase.advance_combat_phase; ``beat`` carries the loop position. Typed
    # ``str`` (not the PhaseBeat enum) to avoid a session_data <-> combat_phase import
    # cycle — combat_phase owns combat_phase.PhaseBeat (a StrEnum whose members ==
    # these strings) and compares against it. Defaults to the declaration beat.
    beat: str = "declaration"
    # Declarations collected in Beat 1 (actor_id -> opaque declaration dict; typed by
    # M4.2), consumed in Beat 2, cleared at the wrap loop-back.
    pending_declarations: dict[str, dict] = field(default_factory=dict)
    # Reaction availability for the current phase (actor_id -> bool), reset each
    # declaration beat; consumed by Beat-3 reaction windows (M4.x).
    reactions_available: dict[str, bool] = field(default_factory=dict)
    # Phase-scoped AC modifiers (actor_id -> bonus), e.g. Defend's +2 (M4.2, story-002).
    # Set during resolution, cleared at the wrap loop-back so a stance lasts one phase.
    ac_modifiers: dict[str, int] = field(default_factory=dict)
    # Combat-scoped (NOT phase-scoped): flips True after the first attack of the whole
    # encounter resolves, never resets. Feeds the M4.5 dramatic-dice "first_attack"
    # signal so the opening strike earns the dice (story-004).
    first_attack_resolved: bool = False

    def get_participant(self, participant_id: str) -> CombatParticipant | None:
        for p in self.participants:
            if p.id == participant_id:
                return p
        return None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> CombatState:
        """Rebuild a CombatState from the asdict() shape to_dict() produces (the read-side
        inverse, M4.1 story-002). Each participant dict is reconstructed into a CombatParticipant
        so loaded state carries instances, not raw dicts. Phase fields and any field absent from
        rows written before they existed fall back to the dataclass defaults via data.get(...).
        ``beat`` stays a plain str — combat_phase is NOT imported here, to avoid the
        session_data <-> combat_phase cycle the class docstring notes."""
        return cls(
            combat_id=data["combat_id"],
            participants=[CombatParticipant(**p) for p in data["participants"]],
            initiative_order=data["initiative_order"],
            round_number=data.get("round_number", 1),
            current_turn_index=data.get("current_turn_index", 0),
            location_id=data.get("location_id", ""),
            beat=data.get("beat", "declaration"),
            pending_declarations=data.get("pending_declarations", {}),
            reactions_available=data.get("reactions_available", {}),
            ac_modifiers=data.get("ac_modifiers", {}),
            first_attack_resolved=data.get("first_attack_resolved", False),
        )


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
    resonance: ResonanceTrack = field(default_factory=ResonanceTrack)
    veil_ward: VeilWardState = field(default_factory=VeilWardState)
    concentration: ConcentrationState = field(default_factory=ConcentrationState)
    corruption_level: int = 0
    patron_id: str = "none"
    creation_state: CreationState | None = None
    onboarding_beat: int | None = None
    pre_combat_agent_type: str | None = None
    pre_dispatch_agent_type: str | None = None
    pre_blacksmith_agent_type: str | None = None

    # Per-encounter weapon durability state (story-003). A weapon takes 1 hit per
    # encounter (2 on a crit vs a heavily-armored target); set during packet
    # resolution (combat_turn._resolve_attack_packet on any player swing), consumed
    # and reset at end_combat. Lives here, not on CombatParticipant, because the
    # flag spans the whole encounter rather than a single combat_state snapshot.
    weapon_used_this_encounter: bool = False
    weapon_crit_vs_heavy: bool = False

    # Draethar Inner Fire is once-per-encounter (story-005, M3.4). Set by the inner_fire tool,
    # reset at both encounter boundaries beside the weapon flags above.
    draethar_inner_fire_used: bool = False

    # Cached data for hot context (updated by background process, read by voice loop)
    cached_location_name: str = ""
    cached_npc_names: list[str] = field(default_factory=list)
    cached_quest_summaries: list[str] = field(default_factory=list)
    # M6 reveal signal: element ids surfaced by check(discover) this turn, appended by the
    # E.HIDDEN_REVEALED handler. story-003's hot-layer assembly reads these to surface the
    # revealed target same-turn, then clears the list.
    recently_revealed_element_ids: list[str] = field(default_factory=list)

    # Session metrics tracking
    session_xp_earned: int = 0
    session_items_found: list[str] = field(default_factory=list)
    session_quests_progressed: list[str] = field(default_factory=list)
    session_locations_visited: list[str] = field(default_factory=list)
    ending_requested: bool = False
    player_disconnected: bool = False
    disconnect_time: float = 0.0

    @property
    def in_onboarding(self) -> bool:
        return self.onboarding_beat is not None

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
