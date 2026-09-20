from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

from livekit import rtc

import combat_reaction_contest
import reaction_spend
import reaction_windows
from caster_state import ConcentrationState, ResonanceTrack
from combat_participant import CombatParticipant
from event_bus import EventBus
from party_state import PartyMember, PartyState
from token_tracker import TokenTracker

if TYPE_CHECKING:
    from background_process import BackgroundProcess

MAX_RECENT_EVENTS = 20
MAX_COMPANION_MEMORIES = 20


@dataclass(frozen=True)
class AuthenticatedActor:
    player_id: str
    generation: int
    validator: Callable[[str, int], None] = field(repr=False, compare=False)


@dataclass
class CompanionState:
    id: str
    name: str
    # Session-start snapshot: the static companion prompt is cached without level in its key.
    # Mid-session gains reach the DM through the Resolve response; this catches up next session.
    player_level: int = 1
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
class DeEscalationState:
    """Tier-3 structured de-escalation scene state (M15 story-001). Scene-scoped, nested on
    CombatState. ``cumulative_shift`` is the per-enemy net ladder-step accumulator the
    surrender gate (combat_resolution.resolve_argument_round) reads; ``enemy_dispositions``
    is the per-enemy ladder-clamped disposition each round's DC derives from. round_counter
    advancement and enemy iteration are story-002 orchestration concerns."""

    round_counter: int = 0
    enemy_dispositions: dict[str, str] = field(default_factory=dict)
    cumulative_shift: dict[str, int] = field(default_factory=dict)


@dataclass
class CombatState:
    combat_id: str
    participants: list[CombatParticipant]
    initiative_order: list[str]  # participant IDs in initiative order
    round_number: int = 1
    current_turn_index: int = 0
    location_id: str = ""
    # Encounter faction (story-002 inc 5): the faction the enemies belong to, sourced at
    # combat_init from the encounter's stance_gate.faction (or an explicit encounter faction).
    # Read at combat_end to attribute the outcome to faction reputation — killing its members
    # lowers standing, a peaceful de-escalation raises it. None when the encounter has no faction.
    faction_id: str | None = None

    # 4-beat phase machine (M4.1, story-001). The deterministic engine lives in
    # combat_phase.advance_combat_phase; ``beat`` carries the loop position. Typed
    # ``str`` (not the PhaseBeat enum) to avoid a session_data <-> combat_phase import
    # cycle — combat_phase owns combat_phase.PhaseBeat (a StrEnum whose members ==
    # these strings) and compares against it. Defaults to the declaration beat.
    beat: str = "declaration"
    # Declarations collected in Beat 1 (actor_id -> opaque declaration dict; typed by
    # M4.2), consumed in Beat 2, cleared at the wrap loop-back.
    pending_declarations: dict[str, dict] = field(default_factory=dict)
    # Round budget/spend state per eligible player; ownership lives on CombatParticipant.
    # Players only by design: a reaction is an archetype technique, and enemy action_pool entries
    # carry no catalog id. The wrap loop-back clears it. Absent actor => no budget (never a free spend).
    reactions_available: dict[str, dict] = field(default_factory=dict)
    # Phase-scoped AC modifiers (actor_id -> bonus), e.g. Defend's +2 (M4.2, story-002).
    # Set during resolution, cleared at the wrap loop-back so a stance lasts one phase.
    ac_modifiers: dict[str, int] = field(default_factory=dict)
    focus_marks: dict[str, dict[str, str]] = field(default_factory=dict)
    # Combat-scoped (NOT phase-scoped): flips True after the first attack of the whole
    # encounter resolves, never resets. Feeds the M4.5 dramatic-dice "first_attack"
    # signal so the opening strike earns the dice (story-004).
    first_attack_resolved: bool = False
    # Diplomat de-escalation (M4.6a story-004). Combat-scoped, never reset within an encounter.
    # ``deescalated`` flips True when a de-escalation argument lands; _wrap reads it to end
    # combat with outcome "deescalated".
    deescalated: bool = False
    # Tier-3 structured de-escalation scene (M15 story-001). Additive to the MVP flags above —
    # multi-round argument state (round_counter + per-enemy disposition/cumulative-shift maps).
    deescalation_scene: DeEscalationState = field(default_factory=DeEscalationState)
    # The ENCOUNTER-scoped Veil Ward (M24 story-004): {"source": str, "rounds_remaining": int|None},
    # or None when the fight is unwarded. A plain dict, like CombatParticipant.conditions — JSONB-native,
    # so it round-trips through combat_instances.data without a nested-dataclass rebuild.
    #
    # This is the ward's ONE home for the encounter scope; location wards live in the veil_wards table
    # (veil_ward_scope_model.md §2 — one home each, no dual state). Deleting the combat row IS the
    # encounter duration, so nothing has to tear this down. story-006 seeds it in combat_init and ticks
    # rounds_remaining at the WRAP beat, beside tick_conditions.
    veil_ward: dict | None = None
    # Enemy declarations HELD for Beat 3 (M29, story-016), initiative-ordered, popped as each
    # resolves. The ally band commits first and the enemy band waits here, so a reload mid-window
    # finds the enemy's turn still pending rather than silently deleted. Each entry:
    #   {"seq": int, "actor_id": str, "declaration": <raw decl dict>, "initiative": int,
    #    "roll": <serialize_roll shape> | None, "opened": [<stage>, ...]}
    # ``opened`` is the position marker the pump reads (combat_hold): a non-attack action has no
    # roll, so the roll alone cannot say which windows this action has already offered.
    # JSONB-native (plain dicts, like veil_ward) so it round-trips with no nested rebuild.
    held_actions: list[dict] = field(default_factory=list)
    # The reaction window the machine is PAUSED on, or None. Surfaced to the DM verbatim in
    # resolve_phase's `next.waiting_on` — the DM never guesses a window id (constraint 6).
    # See reaction_windows.open_window_for for the shape.
    open_window: dict | None = None

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
        reactions_available = reaction_spend.normalize(data.get("reactions_available", {}))
        held_actions = combat_reaction_contest.normalize_held_actions(data.get("held_actions", []), reactions_available)
        return cls(
            combat_id=data["combat_id"],
            participants=[CombatParticipant(**p) for p in data["participants"]],
            initiative_order=data["initiative_order"],
            round_number=data.get("round_number", 1),
            current_turn_index=data.get("current_turn_index", 0),
            location_id=data.get("location_id", ""),
            faction_id=data.get("faction_id"),
            beat=data.get("beat", "declaration"),
            # A row written before story-017 can carry a REACTION pre-declaration, whose type
            # resolve_declaration no longer knows (see reaction_spend.drop_pre_declared_reactions).
            pending_declarations=reaction_spend.drop_pre_declared_reactions(data.get("pending_declarations", {})),
            # Normalized, not passed through: rows written before story-017 carry dict[str, bool]
            # on the field story-018 reads for the reaction binding (see reaction_spend.normalize).
            reactions_available=reactions_available,
            ac_modifiers=data.get("ac_modifiers", {}),
            focus_marks=data.get("focus_marks", {}),
            first_attack_resolved=data.get("first_attack_resolved", False),
            deescalated=data.get("deescalated", False),
            deescalation_scene=DeEscalationState(**data.get("deescalation_scene", {})),
            # Plain dict (or None) — no rebuild. Absent on rows written before story-004.
            veil_ward=data.get("veil_ward"),
            # Plain dicts — no rebuild. Absent on rows written before story-016, which rehydrate
            # with no held actions and no open window: a legacy combat is simply not mid-pause.
            held_actions=held_actions,
            open_window=reaction_windows.upgrade_legacy_window(
                data.get("open_window"), data.get("held_actions", []), data["participants"]
            ),
        )


@dataclass
class CreationState:
    phase: str = "prologue"  # prologue | awakening | calling | devotion | identity | complete
    race: str | None = None
    class_choice: str | None = None
    deity: str | None = None
    name: str | None = None
    backstory: str | None = None


@dataclass(frozen=True)
class SpecializationTap:
    """A LiveKit-verified L5 specialization tap awaiting resolution by the ``select`` verb.

    ``player_id`` comes from ``DataPacket.participant.identity``, which IS the player_id
    (see participant_lifecycle, which compares it directly) — so the tap knows exactly whose
    fork was tapped, with no mapping to build and no chance for a model to get it wrong.

    It is carried here rather than rendered into the DM instruction (decision 5829eecd76eb):
    in the tie this identity exists to break — two same-archetype L5 members, both unresolved —
    a model that mis-copied the id would pass every validation check and permanently write one
    member's choice onto the other's write-once row. ``select`` honours the ticket only when
    BOTH the milestone and the option match the call, it is still FRESH, and clears it after the
    commit.

    ``created_at`` is what keeps the one-shot from latching. The only clear is a ``select`` that
    both commits AND still matches, so a tap the DM never turned into a tool call — or one whose
    call raised — would otherwise leave the ticket standing forever, and a DIFFERENT member's later
    voice ``select`` naming the same milestone and option would be redirected onto the original
    tapper's write-once row (concern fd1480a0ac96). The ticket only has to survive the single
    ``generate_reply`` the tap triggers; past that window it is stale evidence, and falling back to
    select's sole-claimant scan is strictly safer than honouring it.
    """

    player_id: str
    milestone_id: str
    specialization_id: str
    # Monotonic, not wall clock: this measures elapsed time, and a clock step must not resurrect an
    # expired ticket. compare=False so two tickets describing the same tap stay equal.
    created_at: float = field(default_factory=time.monotonic, compare=False)


@dataclass
class SessionData:
    player_id: str
    location_id: str
    party: PartyState = field(init=False)
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    room: rtc.Room | None = field(default=None, repr=False)
    _actor_binding: ContextVar[str | AuthenticatedActor | None] = field(
        default_factory=lambda: ContextVar("actor_player_id", default=None),
        init=False,
        repr=False,
        compare=False,
    )
    event_bus: EventBus = field(default_factory=EventBus)
    world_time: str = "evening"
    combat_state: CombatState | None = None
    # HUD MIRROR of the location-scoped Veil Ward (M24 story-004): the dict read_active_ward last
    # returned for this session's location, or None. Refreshed at hydration, on tool raise/dismiss,
    # and on arrival.
    #
    # NOT the cast-path authority, and nothing correctness-bearing may read it. The cast path calls
    # ward_resolution.resolve_scope_ward, which queries the DB — that is what makes the model's lazy
    # expiry real (scope_model §"Durations need no world clock": nothing sweeps veil_wards; an expired
    # ward is simply not returned by the next read).
    #
    # Consequence, accepted by the settled model: a ward that expires mid-session leaves the HUD
    # indicator lit until the party next moves, raises, or dismisses. Casts stay correct throughout,
    # because they read the DB. M24 adds no tick loop to fire a proactive "the ward drops" event.
    location_ward: dict | None = None
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
    # One-shot owner ticket for the L5 specialization fork (M28 story-008): set by
    # SpecializationTapHandler from the verified sender, consumed and cleared by select.
    pending_specialization_tap: SpecializationTap | None = None
    # Serialises every path that saves or adopts a whole combat_state — start and end included — so
    # no holder writes back a snapshot that predates another holder's change. Readers do not take
    # it. Held for the WHOLE call and acquired BEFORE any DB transaction: an end released before its
    # commit lets a retried end pay the party twice, and a writer that took it inside a transaction
    # could hold a row a lock-holding resolver is waiting on. Combat is session-scoped and lives in
    # one process; a combat resumed by a second agent process would still need a DB-level token.
    combat_state_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)

    # Per-encounter weapon durability state moved PER MEMBER onto PartyMember (M18 story-003):
    # a weapon takes 1 hit per encounter (2 on a crit vs a heavily-armored target), armed on the
    # SWINGING member (combat_packet) and accrued per-member at end_combat, so a non-primary
    # member's swings accrue their own weapon. See PartyMember.weapon_used / weapon_crit_vs_heavy.

    # Draethar Inner Fire is once-per-encounter (story-005, M3.4). Set by the inner_fire tool,
    # reset at both encounter boundaries beside the per-member weapon flags.
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
    tokens: TokenTracker = field(default_factory=TokenTracker)
    session_xp_earned: int = 0
    session_items_found: list[str] = field(default_factory=list)
    session_quests_progressed: list[str] = field(default_factory=list)
    session_locations_visited: list[str] = field(default_factory=list)
    ending_requested: bool = False
    player_disconnected: bool = False
    disconnect_time: float = 0.0

    # The warm-layer loop, owned by the SESSION rather than by the agent that built it: it is
    # constructed once (ExplorationAgent._enter, if absent) and survives every mode handoff,
    # so the DM keeps a warm layer while a CombatAgent holds the floor. Not serialized.
    background: BackgroundProcess | None = field(default=None, repr=False, compare=False)

    # Session-scoped, all three, because the end-of-session recap covers the SESSION and an
    # agent instance only ever sees one slice of it: a handback from combat builds a NEW
    # ExplorationAgent, so anything the recap reads off `self` restarts at every fight.
    session_start_time: float = field(default_factory=time.time)
    # One transcript file per session, seeded by the first agent to enter and appended to by
    # every agent after it (BaseGameAgent._enter). TranscriptLogger mints a fresh timestamped
    # path when given none, so per-agent handles meant the recap read only the last agent's half.
    transcript_path: str | None = None
    # The handle agent.py's on_session_end joins. AgentSession emits "close" synchronously
    # (rtc/event_emitter.py), so the handler can only spawn the work — and an unjoined task
    # races room.disconnect(), which makes publish_game_event drop the recap.
    session_end_task: asyncio.Task | None = field(default=None, repr=False, compare=False)
    multiplayer_owner: object | None = field(default=None, repr=False, compare=False)
    multiplayer_close_task: asyncio.Task | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.party = PartyState.solo(self.player_id, patron_id=self.patron_id)

    def __setattr__(self, name: str, value: object) -> None:
        # Per-member write contract (concern 3ec54e78cae8): resonance/veil_ward/concentration/
        # corruption_level are all @property read + setter write delegating to party.primary
        # below — ONE uniform contract over a PartyMember. patron_id is the SINGLE documented
        # exception: it stays a real dataclass field (like player_id) rather than a delegated
        # @property so pyright keeps validating every ~120 SessionData(...) construction call
        # site by name/type — a property has no positional/keyword construction slot to check.
        # party.primary is seeded from player_id/patron_id in __post_init__; this override keeps
        # the two copies from drifting afterward — player_id by rejecting reassignment outright
        # (it's write-once in prod), patron_id by mirroring writes into party.primary. The
        # sanctioned multi-PC write path for a non-primary caster is member_state(pid), NOT the
        # session.* facade (which always resolves to the primary member).
        if name == "player_id" and "player_id" in self.__dict__:
            raise AttributeError("player_id is write-once")
        if name == "patron_id" and isinstance(value, str) and "party" in self.__dict__:
            self.party.primary.patron_id = value
        super().__setattr__(name, value)

    # resonance/veil_ward/concentration/corruption_level below share ONE per-member write
    # contract (concern 3ec54e78cae8): @property read + setter write, each delegating to
    # party.primary.<field>. The facade resolves to the PRIMARY member — a non-primary
    # caster's state is reached via member_state(pid), the sanctioned multi-PC accessor.
    @property
    def resonance(self) -> ResonanceTrack:
        return self.party.primary.resonance

    @resonance.setter
    def resonance(self, value: ResonanceTrack) -> None:
        self.party.primary.resonance = value

    @property
    def concentration(self) -> ConcentrationState:
        return self.party.primary.concentration

    @concentration.setter
    def concentration(self, value: ConcentrationState) -> None:
        self.party.primary.concentration = value

    @property
    def corruption_level(self) -> int:
        return self.party.primary.corruption_level

    @corruption_level.setter
    def corruption_level(self, value: int) -> None:
        self.party.primary.corruption_level = value

    def member_state(self, player_id: str) -> PartyMember:
        """Return the PartyMember for ``player_id`` — the sanctioned multi-PC per-member accessor.

        Unlike the resonance/veil_ward/concentration/corruption_level facade properties (which
        always resolve to the primary member), this reaches ANY party member's isolated state,
        so a non-primary caster's writes land on their own object. Fails loud on an unknown id
        (an id not in this session's party is a caller error, not a silent default) — the SSOT is
        party.member_ids.
        """
        member = self.party.member(player_id)
        if member is None:
            raise ValueError(f"No party member with player_id {player_id!r}")
        return member

    @property
    def actor_player_id(self) -> str:
        actor = self._actor_binding.get()
        if actor is None:
            raise RuntimeError("No actor is bound to the current DM turn")
        return actor.player_id if isinstance(actor, AuthenticatedActor) else actor

    @contextmanager
    def _bind_actor(self, player_id: str) -> Iterator[None]:
        self.member_state(player_id)
        token = self._actor_binding.set(player_id)
        try:
            yield
        finally:
            self._actor_binding.reset(token)

    @contextmanager
    def _bind_authenticated_actor(
        self, player_id: str, generation: int, validator: Callable[[str, int], None]
    ) -> Iterator[None]:
        self.member_state(player_id)
        actor = AuthenticatedActor(player_id, generation, validator)
        token = self._actor_binding.set(actor)
        try:
            yield
        finally:
            self._actor_binding.reset(token)

    def require_reaction_actor(self) -> AuthenticatedActor:
        actor = self._actor_binding.get()
        if not isinstance(actor, AuthenticatedActor):
            raise RuntimeError("No authenticated actor is bound to the current DM turn")
        self.member_state(actor.player_id)
        actor.validator(actor.player_id, actor.generation)
        return actor

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
