from __future__ import annotations

import uuid
from collections import deque
from dataclasses import asdict, dataclass, field

from livekit import rtc

from caster_state import ConcentrationState, ResonanceTrack, VeilWardState
from event_bus import EventBus
from party_state import PartyState

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
class CombatParticipant:
    id: str
    name: str
    type: str  # "player", "enemy", "companion", "temporary_hollowed" — use is_ally for the band check
    initiative: int
    hp_current: int
    hp_max: int
    ac: int
    attributes: dict = field(default_factory=lambda: {"strength": 10, "dexterity": 10})
    level: int = 1
    is_fallen: bool = False
    # Instant death (M4.4 story-002): a single hit whose overkill (excess damage past 0) >= hp_max
    # kills outright — skips the Fallen state and death saves entirely. Distinct from is_fallen
    # (fallen = dying/making saves; dead = gone). Set at the damage site (combat_support); the pure
    # _wrap ends combat without a death-save beat. Serializes via asdict, defaults False for old rows.
    is_dead: bool = False
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
    # Active status conditions (M4.3, story-002). Each is a plain JSON-native dict
    # {type, duration, source, stacks, stage?} produced by conditions.apply_condition;
    # the phase engine's Beat-4 wrap ticks them (combat_phase._wrap). Serializes via asdict
    # and falls back to [] for rows written before the field existed. Cross-encounter
    # persistence (Wounded/Exhausted/Hollowed) is story-004's migration-050 concern.
    conditions: list[dict] = field(default_factory=list)
    # Encounter-role overlay (M4.7, story-001). ``role`` is the assigned EncounterRole
    # (minion/standard/elite/boss/named) and the rest are the role-derived modifiers
    # encounter_roles.derive_role_stats produces at combat init. ``attack_mod``/``dc_mod``/
    # ``damage_mult`` are read by the resolver (check_resolution_attack/save) to scale this
    # participant's to-hit / save-DC / damage; ``legendary_actions`` + ``signature_ability``
    # scaffold the Boss runtime (firing is story-003). All default to identity so players and
    # pre-M4.7 enemy rows resolve unchanged, and serialize via asdict / fall back on from_dict
    # for rows written before the fields existed (same pattern as enhancers/conditions).
    role: str = "standard"
    attack_mod: int = 0
    damage_mult: float = 1.0
    dc_mod: int = 0
    legendary_actions: int = 0
    signature_ability: dict | None = None
    # Loot & currency overlay (M4.7, story-002). ``category`` is the enemy's creature category
    # (humanoid/beast/hollow_drift/hollow_rend/construct/undead/named) and ``loot_table_id`` points
    # at its content/loot_tables.json table. combat_init carries both off the template enemy; on
    # victory _end_combat_db reads them to roll role-scaled loot (derive_role_loot) and currency
    # (calculate_currency_drop). Empty-string defaults so players/companions and pre-M4.7 enemy
    # rows serialize via asdict / fall back on from_dict unchanged (same pattern as the role fields).
    category: str = ""
    loot_table_id: str = ""
    # Saving-throw proficiencies (M13 close-fix): the attribute save names this participant is
    # proficient in (e.g. ["wisdom", "charisma"]), sourced from players.data at combat init for
    # a player. resolve_saving_throw adds the proficiency bonus when the rolled save is listed —
    # so a WIS-proficient target resists an enemy-inflicted Frightened as the rules intend.
    # Defaults to [] (enemies/companions and pre-fix rows carry none; from_dict falls back).
    saving_throw_proficiencies: list[str] = field(default_factory=list)

    @property
    def is_ally(self) -> bool:
        """True when this participant sits on the player's side (player or companion).

        Single source of truth for the ally/enemy band — consumers (HUD packet builder,
        initiative tie-break, future role logic) read this rather than re-encoding the
        type taxonomy. Enemies and temporary_hollowed (a Stage-2+ player-turned-echo
        that fights AGAINST the party) both read False.
        """
        return self.type in ("player", "companion")


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
    # Diplomat de-escalation (M4.6a story-004). Combat-scoped, never reset within an encounter.
    # ``deescalated`` flips True when a de-escalation argument lands; _wrap reads it to end
    # combat with outcome "deescalated". ``deescalation_used`` flips True on any attempt
    # (success or failure) so de-escalate can be tried at most once per encounter (spec L183).
    deescalated: bool = False
    deescalation_used: bool = False

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
            deescalated=data.get("deescalated", False),
            deescalation_used=data.get("deescalation_used", False),
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
    party: PartyState = field(init=False)
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
    patron_id: str = "none"
    creation_state: CreationState | None = None
    onboarding_beat: int | None = None
    pre_combat_agent_type: str | None = None
    pre_dispatch_agent_type: str | None = None
    pre_blacksmith_agent_type: str | None = None

    # Per-encounter weapon durability state (story-003). A weapon takes 1 hit per
    # encounter (2 on a crit vs a heavily-armored target); set during packet
    # resolution (combat_packet._resolve_one_packet on any player swing), consumed
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

    def __post_init__(self) -> None:
        self.party = PartyState.solo(self.player_id, patron_id=self.patron_id)

    def __setattr__(self, name: str, value: object) -> None:
        # player_id/patron_id stay real dataclass fields (not delegated @property, unlike
        # resonance/veil_ward/concentration/corruption_level below) so pyright keeps validating
        # every ~120 SessionData(...) construction call site by name/type. party.primary is
        # seeded from them in __post_init__; this override keeps the two copies from drifting
        # afterward — player_id by rejecting reassignment outright (it's write-once in prod),
        # patron_id by mirroring writes into party.primary.
        if name == "player_id" and "player_id" in self.__dict__:
            raise AttributeError("player_id is write-once")
        if name == "patron_id" and isinstance(value, str) and "party" in self.__dict__:
            self.party.primary.patron_id = value
        super().__setattr__(name, value)

    @property
    def resonance(self) -> ResonanceTrack:
        return self.party.primary.resonance

    @property
    def veil_ward(self) -> VeilWardState:
        return self.party.primary.veil_ward

    @property
    def concentration(self) -> ConcentrationState:
        return self.party.primary.concentration

    @property
    def corruption_level(self) -> int:
        return self.party.primary.corruption_level

    @corruption_level.setter
    def corruption_level(self, value: int) -> None:
        self.party.primary.corruption_level = value

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
