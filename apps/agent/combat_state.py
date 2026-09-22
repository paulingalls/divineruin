from __future__ import annotations

from dataclasses import asdict, dataclass, field

import combat_reaction_contest
import reaction_spend
import reaction_windows
from combat_participant import CombatParticipant


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
