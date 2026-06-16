"""Pure 4-beat combat phase engine (M4.1, story-001).

Zero IO, zero async — the deterministic heart of phase-based combat, mirroring
``combat_resolution.py``'s pure style. ``advance_combat_phase`` advances ONE beat
per call: declaration -> resolution -> narration -> wrap -> (loop to declaration |
combat_end).

Mechanical attack resolution (``check_resolution.resolve_attack``) and side-effect
application (Resonance decay, death-save rolls, DB persistence) live in orchestration
(story-003); this module only computes beat transitions, ordered resolution packets,
and the wrap beat's effect signals.
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field
from enum import StrEnum

from declarations import Declaration, resolve_declaration
from session_data import CombatState

# Phase-canonical Resonance decay: the wrap beat sheds one step per phase
# (gm_combat:191). Casting must NOT also decay in combat — see decision
# resonance-decay-phase-canonical and story-007 (suppress cast-paced decay in combat).
_RESONANCE_DECAY_PER_PHASE = 1

# Death is three failed death saves; stabilization is three successes
# (see combat_resolution.resolve_death_save).
_DEATH_SAVE_LIMIT = 3
_STABILIZE_LIMIT = 3

# Initiative tie-break: player before companion before enemy, then higher DEX
# (gm_combat:145). Lower number = higher priority.
_TYPE_PRIORITY = {"player": 0, "companion": 1, "enemy": 2}


class PhaseBeat(StrEnum):
    """The four beats of a combat phase. StrEnum so members serialize transparently
    through ``asdict`` -> ``json.dumps`` when carried on ``CombatState.beat``."""

    DECLARATION = "declaration"
    RESOLUTION = "resolution"
    NARRATION = "narration"
    WRAP = "wrap"


@dataclass(frozen=True)
class ResolutionPacket:
    """One declaration's resolution envelope, ordered by initiative in Beat 2.

    ``declaration`` is a typed ``Declaration`` (M4.2, story-002): ``_resolve_packets``
    classifies each pending raw dict through ``resolve_declaration``. ``dramatic`` is a
    placeholder filled by the dramatic-dice evaluator (M4.5). Mechanical resolution (the
    attack roll, Defend AC application) is applied by orchestration via ``combat_turn``.
    """

    actor_id: str
    declaration: Declaration
    initiative: int
    dramatic: bool = False


@dataclass(frozen=True)
class WrapOutcome:
    """Beat-4 effect signals for orchestration to apply.

    Kept as a return value (not applied here) so the engine stays pure over
    ``CombatState`` — Resonance and persistence live on ``SessionData``, not
    ``CombatState``.
    """

    death_saves_due: list[str]
    resonance_decay: int
    combat_ended: bool
    outcome: str | None  # "victory" | "defeat" | None


@dataclass(frozen=True)
class PhaseAdvance:
    """Return envelope: which beat was completed, plus its outputs (packets only
    after RESOLUTION; wrap only after WRAP)."""

    beat_completed: PhaseBeat
    packets: list[ResolutionPacket] = field(default_factory=list)
    wrap: WrapOutcome | None = None


def advance_combat_phase(
    state: CombatState,
    declarations: dict[str, dict] | None = None,
    rng: random.Random | None = None,
) -> tuple[CombatState, PhaseAdvance]:
    """Advance the combat phase machine by exactly one beat.

    Pure: returns a new ``CombatState`` (deep-copied) and never mutates the input.
    ``rng`` is an unused forward seam for M4.2 resolution rolls; M4.1 has no
    randomness, so the engine is trivially deterministic.
    """
    next_state = copy.deepcopy(state)

    if state.beat == PhaseBeat.DECLARATION:
        if not declarations:
            raise ValueError("declaration beat requires declarations")
        # Validate every declaration's shape at declare time so a bad one fails loud
        # here (the tool layer translates ValueError -> ToolError) rather than at the
        # later resolution beat. Raw dicts are still what's stored/persisted.
        for raw in declarations.values():
            resolve_declaration(raw)
        next_state.pending_declarations = dict(declarations)
        next_state.reactions_available = {p.id: True for p in next_state.participants}
        next_state.beat = PhaseBeat.RESOLUTION
        return next_state, PhaseAdvance(beat_completed=PhaseBeat.DECLARATION)

    if state.beat == PhaseBeat.RESOLUTION:
        packets = _resolve_packets(next_state)
        next_state.beat = PhaseBeat.NARRATION
        return next_state, PhaseAdvance(beat_completed=PhaseBeat.RESOLUTION, packets=packets)

    if state.beat == PhaseBeat.NARRATION:
        # Narration is the DM's job (external/LLM); the engine only transitions.
        next_state.beat = PhaseBeat.WRAP
        return next_state, PhaseAdvance(beat_completed=PhaseBeat.NARRATION)

    if state.beat == PhaseBeat.WRAP:
        wrap = _wrap(next_state)
        if not wrap.combat_ended:
            next_state.round_number += 1
            next_state.current_turn_index = 0
            next_state.pending_declarations = {}
            next_state.reactions_available = {}
            next_state.ac_modifiers = {}  # phase-scoped Defend bonuses expire here
            next_state.beat = PhaseBeat.DECLARATION
        return next_state, PhaseAdvance(beat_completed=PhaseBeat.WRAP, wrap=wrap)

    raise ValueError(f"unknown combat beat: {state.beat!r}")


def _resolve_packets(state: CombatState) -> list[ResolutionPacket]:
    """Order pending declarations by initiative (desc; tie: player > companion >
    enemy, then higher DEX) and wrap each into a ResolutionPacket. No narration.

    This is the single source of truth for per-phase RESOLUTION ordering, and it
    applies the spec tie-break (gm_combat:145) that roll_initiative does not.
    CombatState.initiative_order (set once by combat_init via roll_initiative,
    sorted by total only) is the start-of-combat DISPLAY order consumed by the
    HUD/warm prompts — intentionally NOT the resolution-ordering source, so the
    two can differ on a tie. Not reconciled here by design.
    """
    by_id = {p.id: p for p in state.participants}

    def sort_key(actor_id: str) -> tuple[int, int, int]:
        p = by_id.get(actor_id)
        if p is None:
            return (0, 0, 0)
        dex = p.attributes.get("dexterity", 10)
        return (p.initiative, -_TYPE_PRIORITY.get(p.type, 9), dex)

    ordered_ids = sorted(state.pending_declarations, key=sort_key, reverse=True)
    return [
        ResolutionPacket(
            actor_id=actor_id,
            declaration=resolve_declaration(state.pending_declarations[actor_id]),
            initiative=by_id[actor_id].initiative if actor_id in by_id else 0,
        )
        for actor_id in ordered_ids
    ]


def _wrap(state: CombatState) -> WrapOutcome:
    """Compute Beat-4 effect signals and the end-condition. Pure read over
    participants; mutations/persistence are the orchestrator's job."""
    death_saves_due = [
        p.id
        for p in state.participants
        if p.is_fallen and p.death_save_successes < _STABILIZE_LIMIT and p.death_save_failures < _DEATH_SAVE_LIMIT
    ]

    enemies = [p for p in state.participants if p.type == "enemy"]
    # M4.1 scope seam: defeat keys on a SINGLE player participant. Multiplayer
    # party-defeat (all players down) and party-wipe handling are M4.4 (Death &
    # Resurrection); this single-player assumption is intentional for M4.1.
    player = next((p for p in state.participants if p.type == "player"), None)

    combat_ended = False
    outcome: str | None = None
    if enemies and all(p.is_fallen for p in enemies):
        combat_ended, outcome = True, "victory"
    elif player is not None and player.death_save_failures >= _DEATH_SAVE_LIMIT:
        combat_ended, outcome = True, "defeat"

    return WrapOutcome(
        death_saves_due=death_saves_due,
        resonance_decay=_RESONANCE_DECAY_PER_PHASE,
        combat_ended=combat_ended,
        outcome=outcome,
    )
