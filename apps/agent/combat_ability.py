"""In-combat ABILITY (cast) resolution helpers.

Splits the ability-cast concern out of combat_support (story-007): resolving an
in-combat ABILITY declaration through the shared cast logic, the side-channel that
carries the cast result back to the phase loop, action lookup, and enhancer-rider
attachment. Consumed by the phase loop (combat_turn)."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import abilities
import ability_persistence
import combat_ability_save
import combat_enhancers
import spell_casting
from combat_ability_gate import DeclaredAbility
from combat_condition_landing import _land_condition_on_one
from condition_produce import resolve_effective_targets
from mentor_variants import MentorVariant
from resource_costs import gate_pool
from session_data import CombatParticipant, SessionData

if TYPE_CHECKING:
    from declarations import Declaration
    from spell_casting import CastResult


def land_condition_on_participant(
    state,
    attacker: CombatParticipant,
    decl: "Declaration",
    cond_type: str,
    source: str,
    *,
    packet: dict,
) -> bool:
    """Single-target landing rule for the combat producers (the spell path in _resolve_ability_packet
    and the non-spell ability path in _resolve_ability_condition_packet): land ``cond_type`` on
    ``decl.target_id`` (self when absent). Returns True iff it landed. Thin wrapper over
    ``_land_condition_on_one``; ``packet`` receives any release caused by the condition."""
    return _land_condition_on_one(state, decl.target_id, attacker, cond_type, source, packet=packet)


def land_condition_on_participants(
    state, attacker: CombatParticipant, decl: "Declaration", cond_type: str, source: str, *, packet: dict
) -> list[str]:
    """Land ``cond_type`` on EACH participant of a multi-target declaration (M4.8 story-012).

    Resolves the target list: ``decl.target_ids`` (order-preserving dedup) when present, else the
    single ``decl.target_id``, else the caster (self-cast). The cap was already enforced at the
    declare-gate (combat_packet via spells.normalize_target_list); dedup here just prevents
    double-voicing the same ally. Returns the participant ids the buff actually LANDED on (an id not
    on the working state, or an immunity no-op, is dropped) — the subset the DM should name."""
    targets = resolve_effective_targets(decl.target_ids, decl.target_id, self_value=None, dedup=True)
    voiced: list[str] = []
    for target_id in targets:
        if _land_condition_on_one(state, target_id, attacker, cond_type, source, packet=packet):
            voiced.append(target_id if target_id is not None else attacker.id)
    return voiced


def condition_ability(resolved: DeclaredAbility | None) -> DeclaredAbility | None:
    """The non-spell, condition-applying declared ability, or None.

    The in-combat ABILITY path resolves spells by default (via _gate_spell / _resolve_cast); a
    non-spell ability that PRODUCES a condition (M4.8 story-005, e.g. bard_inspire) takes the
    dedicated ability-condition path instead. An ability is on that path iff it carries
    ``applies_condition`` AND has no ``spell_id`` — a spell-backed condition ability keeps the
    spell path, where story-004's producer block already applies it (assumption 07d1a208794b).
    Returns None for an unknown action or any spell/non-condition ability."""
    if resolved is None:
        return None
    ability, _variant = resolved
    if ability.applies_condition is not None and ability.spell_id is None:
        return resolved
    return None


def _gate_ability_condition(
    player: dict,
    ability: "abilities.Ability",
    variant: MentorVariant | None = None,
) -> None:
    """Declare-time fail-loud gate for a non-spell condition ability (M4.8 story-005): validate the
    ability's Stamina/Focus with NO writes, mirroring _gate_deescalation / _gate_spell so a bad
    declaration never rolls back a phase that already resolved other actors. resource_costs.gate_pool
    is the sole Focus/Stamina gate; the deduct happens in _resolve_ability_condition_packet."""
    cost = variant.cost if variant is not None else ability.cost
    gate_pool(player, "stamina", cost.stamina, label=ability.name)
    gate_pool(player, "focus", cost.focus, label=ability.name)


async def _deduct_ability_cost(player_id, player, ability, variant, *, persistence, conn) -> None:
    """Spend a condition ability's Stamina/Focus via the gate_pool SSOT and persist against
    ``player_id`` (the declaring member — M14 story-004, was the session primary). Shared by the
    single- and multi-target resolve branches so the deduct lives once; gate_pool fail-louds if the
    cost can't be paid (already pre-gated at declare time)."""
    cost = variant.cost if variant is not None else ability.cost
    new_stamina = gate_pool(player, "stamina", cost.stamina, label=ability.name)
    new_focus = gate_pool(player, "focus", cost.focus, label=ability.name)
    if new_stamina is not None or new_focus is not None:
        await persistence.update_player_resources(player_id, stamina=new_stamina, focus=new_focus, conn=conn)


async def _resolve_ability_condition_packet(
    session: SessionData,
    attacker: CombatParticipant,
    decl: "Declaration",
    resolved: DeclaredAbility,
    *,
    state,
    conn,
    player: dict | None,
    persistence=ability_persistence,
) -> dict:
    """Resolve a non-spell condition-applying ABILITY in combat (M4.8 story-005, e.g. bard_inspire).

    Resolve the TARGET participant FIRST: self-target (no target_id) is the caster (always present);
    a given target_id that's not on the working state, or one already fallen, WASTES the declaration
    (resolved:False) WITHOUT deducting — you can't buff a target that left or a corpse, and a wasted
    declaration must never burn the ability's Stamina/Focus (mirrors the attack path's wasted-target
    guards). Only once a live target is confirmed do we deduct the cost (pre-gated at declare time via
    _gate_ability_condition) and land applies_condition on it via the shared helper — the mutation
    rides the phase save_combat_state (no extra write). ``player`` is the for_update row from
    prevalidation, reused so the lock is taken once."""
    if state is None or player is None:
        return {"actor_id": attacker.id, "resolved": False, "reason": "no active combat or player"}

    ability, variant = resolved

    # applies_condition is non-None on this path (condition_ability selected it). The source is the
    # base ability id, which differs from decl.action when a mentor variant was declared.
    cond_type = ability.applies_condition

    # Multi-target (M4.8 story-016, e.g. bard_mass_inspire): the cap was validated at the
    # declare-gate (spells.normalize_target_list). Deduct once, land on EACH live ally, and voice
    # the landed set (condition_targets) — mirroring the multi-target spell path. A target gone by
    # resolve time is dropped (partial landing); an all-off-state list lands nothing but still
    # spends the cost (the spell-path convention — the declaration committed to the action).
    if decl.target_ids:
        await _deduct_ability_cost(attacker.id, player, ability, variant, persistence=persistence, conn=conn)
        summary = {
            "actor_id": attacker.id,
            "resolved": True,
            "declaration_type": str(decl.type),
            "action": ability.id,
        }
        if cond_type is not None:
            voiced = land_condition_on_participants(state, attacker, decl, cond_type, source=ability.id, packet=summary)
            if voiced:
                summary["condition_applied"] = cond_type
                summary["condition_targets"] = voiced
        return _with_variant(summary, variant)

    # Single-target (story-005): a given target_id that's not on the working state, or already
    # fallen, WASTES the declaration (resolved:False) WITHOUT deducting — you can't buff a target
    # that left or a corpse, and a wasted declaration must never burn the cost.
    target, waste = _resolve_condition_target(state, attacker, decl)
    if waste is not None:
        return waste
    assert target is not None

    await _deduct_ability_cost(attacker.id, player, ability, variant, persistence=persistence, conn=conn)

    if ability.save is not None:
        summary = combat_ability_save.resolve_hostile_condition(
            state, attacker, target, decl, ability, _land_condition_on_one
        )
        return _with_variant(summary, variant)

    summary = {
        "actor_id": attacker.id,
        "resolved": True,
        "declaration_type": str(decl.type),
        "action": ability.id,
    }
    if cond_type is not None and land_condition_on_participant(
        state, attacker, decl, cond_type, source=ability.id, packet=summary
    ):
        summary["condition_applied"] = cond_type
    return _with_variant(summary, variant)


def _with_variant(summary: dict, variant: MentorVariant | None) -> dict:
    if variant is not None:
        summary["variant_id"] = variant.id
        summary["cultural_attribution"] = variant.cultural_attribution
    return summary


def _resolve_condition_target(state, attacker: CombatParticipant, decl: "Declaration", *, allow_self: bool = True):
    """Resolve the single target of a condition-applying declaration.

    Returns ``(target, None)`` for a live target, or ``(None, waste_summary)`` when the target is
    gone / already fallen / disallowed — a wasted declaration must never apply the condition or
    deduct a cost. ``allow_self`` controls the ``target_id is None`` case: True (default) falls back
    to the caster (a player self-buff); False WASTES it instead — a hostile inflict must never
    self-target (an ABILITY-declared enemy condition action, which skips ATTACK's target_id
    validation, would otherwise make the enemy inflict on ITSELF). Shared by the player ability-
    condition path and the enemy condition-infliction path so the wasted-target contract lives once."""
    target = attacker if decl.target_id is None else state.get_participant(decl.target_id)
    # allow_self=False wastes ANY self-target: the None fallback OR an explicit target_id equal to
    # the attacker's own id — a hostile inflict must never land on its own caster.
    if not allow_self and (decl.target_id is None or (target is not None and target.id == attacker.id)):
        return None, {
            "actor_id": attacker.id,
            "resolved": False,
            "declaration_type": str(decl.type),
            "reason": "condition action requires a non-self target_id",
        }
    if target is None:
        return None, {
            "actor_id": attacker.id,
            "resolved": False,
            "declaration_type": str(decl.type),
            "reason": f"target '{decl.target_id}' not found",
        }
    if target.is_fallen:
        return None, {
            "actor_id": attacker.id,
            "resolved": False,
            "declaration_type": str(decl.type),
            "reason": f"{target.name} already fell",
        }
    return target, None


@dataclass
class AbilityCastOutcome:
    """Side-channel carrying the in-loop ABILITY casts' ``CastResult``s back to the phase loop.

    Each party member may declare one ability per phase (M14 story-004), so results are keyed by the
    caster's participant id (== player_id). The loop reads ``results`` post-commit to seed each
    member's WRAP resonance, flush their deferred client events, and push per-member HUD state — all
    of which must happen after the phase tx commits (story-007). ``results`` stays empty when no
    ability resolved. Concentration is synced IN-LOOP by ``_resolve_ability_packet`` (not here)."""

    results: dict[str, "CastResult"] = field(default_factory=dict)


async def _resolve_ability_packet(
    session: SessionData,
    attacker: CombatParticipant,
    decl,
    *,
    state,
    cast_resolver,
    conn,
    player: dict | None,
    cast_outcome: AbilityCastOutcome,
) -> dict:
    """Resolve one in-combat ABILITY declaration through the shared cast logic (story-007).

    Player-gated: only the player carries a Focus pool + resonance track, so a non-player ABILITY
    (or one missing its action) is a *wasted* packet — enemy/companion casting is later M4.x work.
    Delegates to ``cast_resolver._resolve_cast`` with the cast's own RESONANCE_CHANGED suppressed
    (in combat the phase WRAP push is the single authoritative HUD update), stashing the returned
    CastResult on ``cast_outcome`` for the loop to commit. The returned summary carries the spell
    packet for the DM plus any narrated enhancer riders."""
    if attacker.type != "player":
        return {
            "actor_id": attacker.id,
            "resolved": False,
            "declaration_type": str(decl.type),
            "reason": "ability resolution not yet implemented for non-player actors",
        }
    if not decl.action:
        return {
            "actor_id": attacker.id,
            "resolved": False,
            "declaration_type": str(decl.type),
            "reason": "ability declaration missing an action",
        }

    # Resolve the declaring member (M14 story-004): the cast reads + writes THAT member's own pool
    # (resonance/veil_ward/concentration/player_id), never the primary's. attacker.id == the member's
    # player_id (combat_init builds player participants with id=mid). A missing member falls back to
    # the primary — the same fallback _resolve_cast applies to caster=None — so solo stays identical.
    caster = session.party.member(attacker.id) or session.party.primary
    result = await cast_resolver._resolve_cast(
        session,
        decl.action,
        conn=conn,
        caster=caster,
        player=player,
        target_id=decl.target_id,
        suppress_resonance_changed=True,
    )
    cast_outcome.results[attacker.id] = result
    # Sync concentration into the CASTER's SSOT IN-LOOP (not post-commit): a lower-initiative enemy
    # attack later this same phase runs break_concentration_on_damage, which reads the in-memory
    # concentration to pick which spell to save for and to clear on a failed save. A post-commit sync
    # would leave it stale — the break would save against the OLD spell and, on a break, write None to
    # the DB (clearing the just-cast spell) while the post-commit sync forced memory back to the new
    # spell, diverging from the DB (story-007). _CombatScratchSnapshot captures concentration, so this
    # in-tx mutation is reverted if the phase rolls back. break_concentration_on_damage now reads the
    # DAMAGED member's own concentration (via damaged_player_id, M18 story-004), so a non-primary
    # caster's break resolves against their own pool — matching this per-member SYNC.
    if result.concentration_spell_id is not spell_casting._UNCHANGED:
        caster.concentration.spell_id = cast("str | None", result.concentration_spell_id)
    # Beneficial-condition PRODUCER (M4.8 story-004), in-combat half. _resolve_cast surfaces the
    # produced condition as packet.condition_applied (the OOC players.data write is gated off in
    # combat). In combat the working state is the SSOT, so land it on the TARGET participant here —
    # the mutation rides this phase's save_combat_state. Self-cast (no target_id) falls back to the
    # caster; a target not on the working state narrates nothing (condition_applied dropped) rather
    # than crashing the phase, mirroring the wasted-declaration guards. source=decl.action is the
    # spell id (matching the OOC source=spell_id). Resolved here where attacker/decl/result are
    # already in scope — no outcome re-read in the dispatcher.
    cond_type = result.packet.get("condition_applied")
    if cond_type:
        if decl.target_ids:
            # Multi-target (M4.8 story-012): land on EACH ally participant (cap already enforced at
            # the declare-gate). Surface the voiced ids so the DM names each blessed companion; drop
            # the signal entirely if NONE landed (all off-state / immune).
            voiced = land_condition_on_participants(
                state, attacker, decl, cond_type, source=decl.action, packet=result.packet
            )
            if voiced:
                result.packet["condition_targets"] = voiced
            else:
                result.packet.pop("condition_applied", None)
        elif not land_condition_on_participant(
            state, attacker, decl, cond_type, source=decl.action, packet=result.packet
        ):
            # Target gone, or apply no-op'd (immunity gate) — don't narrate a buff that never landed.
            result.packet.pop("condition_applied", None)
    summary = {
        "actor_id": attacker.id,
        "resolved": True,
        "declaration_type": str(decl.type),
        "action": decl.action,
        "cast": result.packet,
    }
    return _attach_riders(summary, attacker, decl)


def _find_action(participant, action_name) -> dict | None:
    """Find the named action in a participant's action_pool (case-insensitive)."""
    if not action_name:
        return None
    wanted = str(action_name).lower()
    for a in participant.action_pool:
        if a.get("name", "").lower() == wanted:
            return a
    return None


def _attach_riders(summary: dict, attacker, decl) -> dict:
    """Add the actor's narrated enhancer riders to a packet summary, if any.

    Riders are descriptive (non-mechanical) — they carry no HP/AC effect, just the DM
    cue for an enhancer's expansion (Cunning Action's dash/disengage/hide, Hit and Run,
    Command Lesser, Quick Change). Omitted entirely when the actor has none, so a
    no-enhancer declaration keeps its flat summary (AC3: no phantom expansion)."""
    riders = combat_enhancers.declaration_riders(attacker.enhancers, decl)
    if riders:
        summary["riders"] = riders
    return summary
