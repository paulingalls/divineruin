"""Pure 4-beat combat phase engine (M4.1, story-001).

Zero IO, zero async — the deterministic heart of phase-based combat, mirroring
``combat_resolution.py``'s pure style. ``advance_combat_phase`` advances ONE beat
per call: declaration -> resolution -> narration -> wrap -> (loop to declaration |
combat_end).

Mechanical attack resolution (``check_resolution_attack.resolve_attack``) and side-effect
application (Resonance decay, death-save rolls, DB persistence) live in orchestration
(story-003); this module only computes beat transitions, ordered resolution packets,
and the wrap beat's effect signals.
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field
from enum import StrEnum

from conditions import tick_conditions
from declarations import Declaration, resolve_declaration
from encounter_roles import EncounterRole
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
# (gm_combat:145). Lower number = higher priority. The 0/1 band == ally, 2 == enemy
# — for an ally/enemy classification check use CombatParticipant.is_ally instead;
# this table additionally orders WITHIN the ally band (player before companion).
# A Temporary Hollowed echo (M4.4 story-008) acts in the enemy band — it's a hostile combatant.
_TYPE_PRIORITY = {"player": 0, "companion": 1, "enemy": 2, "temporary_hollowed": 2}


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
    outcome: str | None  # "victory" | "defeat" | "deescalated" | None
    # Save-to-clear signals from the Beat-4 condition tick (M4.3, story-002): one
    # {actor_id, type, save, source} per active save-to-clear condition (Frightened today).
    # The engine never rolls — orchestration (story-004 combat_turn) resolves the save and
    # clears the condition on success. Duration-based expiry is already applied to the
    # returned state's participant.conditions; this carries only what needs a roll.
    tick_conditions_due: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class PhaseAdvance:
    """Return envelope: which beat was completed, plus its outputs (packets only
    after RESOLUTION; wrap only after WRAP)."""

    beat_completed: PhaseBeat
    packets: list[ResolutionPacket] = field(default_factory=list)
    wrap: WrapOutcome | None = None
    # Boss legendary actions available for the round just entered (M4.7, story-003): one
    # descriptor per living Boss with budget remaining, populated only on a non-ending WRAP
    # (after the per-round budget reset). The engine SURFACES the available legendary so the
    # DM can narrate the extra Boss beat — taken at the end of another creature's turn
    # (game_mechanics_encounter_roles.md:112-120) — but NEVER auto-fires it. The DM spends it
    # via consume_legendary_action. Empty for every non-WRAP beat and for a terminal wrap.
    legendary_available: list[dict] = field(default_factory=list)


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
        legendary_available: list[dict] = []
        if not wrap.combat_ended:
            next_state.round_number += 1
            next_state.current_turn_index = 0
            next_state.pending_declarations = {}
            next_state.reactions_available = {}
            next_state.ac_modifiers = {}  # phase-scoped Defend bonuses expire here
            # Refresh each living Boss's 1/round legendary budget for the round just entered,
            # then surface what's available so the DM can narrate the extra Boss beat.
            _reset_legendary_actions(next_state)
            legendary_available = _boss_legendaries(next_state)
            next_state.beat = PhaseBeat.DECLARATION
        return next_state, PhaseAdvance(
            beat_completed=PhaseBeat.WRAP, wrap=wrap, legendary_available=legendary_available
        )

    raise ValueError(f"unknown combat beat: {state.beat!r}")


def _reset_legendary_actions(state: CombatState) -> None:
    """Refresh each living Boss's legendary-action budget to 1 for the new round
    (game_mechanics_encounter_roles.md:112 — a Boss takes one legendary action per round).

    Mutates the deep-copied next_state in place at the WRAP loop-back, like the wrap
    condition tick. Non-Boss participants have no legendary budget and are left untouched
    (they stay at the dataclass default of 0). A fallen Boss is skipped — a downed creature
    takes no legendary actions."""
    for p in state.participants:
        if p.role == EncounterRole.BOSS and not p.is_fallen:
            p.legendary_actions = 1


def _boss_legendaries(state: CombatState) -> list[dict]:
    """Descriptors for every living Boss with a legendary action available this round.

    Surfaced on PhaseAdvance.legendary_available so the DM can narrate the extra Boss beat
    (taken at the end of another creature's turn). Carries the Boss's id/name and authored
    ``signature_ability`` so the DM has the move's options; the engine never auto-fires it."""
    return [
        {
            "actor_id": p.id,
            "name": p.name,
            "legendary_actions": p.legendary_actions,
            "signature_ability": p.signature_ability,
        }
        for p in state.participants
        if p.role == EncounterRole.BOSS and not p.is_fallen and p.legendary_actions > 0
    ]


def consume_legendary_action(state: CombatState, boss_id: str) -> CombatState:
    """Spend one of a Boss's legendary actions — the DM fires the extra Boss beat.

    Pure: returns a NEW (deep-copied) CombatState with the named Boss's ``legendary_actions``
    decremented by one; never mutates the input. Fails loud (ValueError -> ToolError at the
    tool layer) if the actor is unknown, not a Boss, or has no legendary action left this
    round, so the DM can never overspend the 1/round budget. The budget refreshes at the next
    WRAP via ``_reset_legendary_actions``."""
    next_state = copy.deepcopy(state)
    boss = next_state.get_participant(boss_id)
    if boss is None:
        raise ValueError(f"unknown participant {boss_id!r}")
    if boss.role != EncounterRole.BOSS:
        raise ValueError(f"{boss_id!r} is not a Boss (role={boss.role!r}); only Bosses have legendary actions")
    if boss.legendary_actions <= 0:
        raise ValueError(f"Boss {boss_id!r} has no legendary action remaining this round")
    boss.legendary_actions -= 1
    return next_state


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
    """Compute Beat-4 effect signals and the end-condition.

    Applies the per-phase condition tick to ``state.participants`` — conditions live ON
    CombatState (the SSOT), so the engine owns advancing them, unlike Resonance/HP/DB which
    live on SessionData and stay the orchestrator's job. ``state`` here is the deep-copied
    next_state, so this never mutates the caller's input. Surfaces save-to-clear signals in
    ``tick_conditions_due``; the engine never rolls them."""
    tick_conditions_due: list[dict] = []
    for p in state.participants:
        survivors, save_events = tick_conditions(p.conditions)
        p.conditions = survivors
        tick_conditions_due.extend({"actor_id": p.id, **event} for event in save_events)

    # Companion auto-stabilize (M4.4 story-002): narrative protection — a companion never dies from
    # the death-save grind. When its failures reach the limit, clamp to the stabilized state (reusing
    # the stabilized vocabulary, no new field) so it drops out of death_saves_due and never ends combat.
    for p in state.participants:
        if p.type == "companion" and p.death_save_failures >= _DEATH_SAVE_LIMIT:
            p.death_save_failures = _DEATH_SAVE_LIMIT - 1
            p.death_save_successes = _STABILIZE_LIMIT

    death_saves_due = [
        p.id
        for p in state.participants
        if p.is_fallen
        and not p.is_dead  # instant-dead (M4.4) skips the Fallen state — never rolls a death save
        and p.death_save_successes < _STABILIZE_LIMIT
        and p.death_save_failures < _DEATH_SAVE_LIMIT
    ]

    enemies = [p for p in state.participants if p.type == "enemy"]
    # Temporary Hollowed echoes (M4.4 story-008): a Stage-2+ Hollowed player who fell rose as one of
    # these in place (the player participant transformed). While any echo lives it blocks combat-end;
    # once all are destroyed the character finally dies (defeat -> the existing combat-end defeat path
    # -> trigger_character_death's Hollowed branch). The echo is not type "player", so the player-
    # defeat gate below stays dormant whenever an echo is present.
    echoes = [p for p in state.participants if p.type == "temporary_hollowed"]
    # M18 multi-PC party defeat: combat ends in defeat only when ALL player participants are
    # terminally down (is_dead or death_save_failures >= _DEATH_SAVE_LIMIT). A standing or
    # still-rolling player keeps combat alive.
    players = [p for p in state.participants if p.type == "player"]

    combat_ended = False
    outcome: str | None = None
    # De-escalation (M4.6a story-004) ends combat BEFORE the victory/defeat gates: a
    # successful Diplomat argument talks the enemies down while they still stand, so it
    # must take precedence over the enemies-all-fallen check (which would never fire here).
    if state.deescalated:
        combat_ended, outcome = True, "deescalated"
    elif echoes and all(e.is_fallen for e in echoes):
        combat_ended, outcome = True, "defeat"
    elif echoes:
        pass  # an undestroyed echo blocks both victory and the (now-moot) player-defeat gate
    elif enemies and all(p.is_fallen for p in enemies):
        combat_ended, outcome = True, "victory"
    elif players and all(p.is_dead or p.death_save_failures >= _DEATH_SAVE_LIMIT for p in players):
        combat_ended, outcome = True, "defeat"

    return WrapOutcome(
        death_saves_due=death_saves_due,
        resonance_decay=_RESONANCE_DECAY_PER_PHASE,
        combat_ended=combat_ended,
        outcome=outcome,
        tick_conditions_due=tick_conditions_due,
    )
