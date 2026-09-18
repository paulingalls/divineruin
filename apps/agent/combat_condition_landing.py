from typing import TYPE_CHECKING

import combat_grapple
import conditions
from condition_produce import resolve_effective_targets
from condition_restrictions import cannot_act
from session_data import CombatParticipant

if TYPE_CHECKING:
    from declarations import Declaration


def _land_condition_on_one(
    state,
    target_id: str | None,
    attacker: CombatParticipant,
    cond_type: str,
    source: str,
    released_from_grapple: list[str] | None = None,
) -> bool:
    """Land a condition (beneficial or hostile) on ONE in-combat participant (M4.8; M13 story-002
    adds the hostile caller). Self-target (``target_id`` None) falls back to the caster; a given id
    is looked up on the working ``state``. Returns True iff it actually landed (``has_condition``) —
    a target not on the state, or an immunity no-op, returns False so the caller drops the signal.
    The mutation rides save_combat_state."""
    cond_target = attacker if target_id is None else state.get_participant(target_id)
    if (
        cond_target is None
        or cond_type in cond_target.condition_immunities
        or (cond_type == "prone" and cond_target.prone_immunity)
    ):
        return False
    cond_target.conditions = conditions.apply_condition(cond_target.conditions, cond_type, source=source)
    landed = conditions.has_condition(cond_target.conditions, cond_type)
    if landed and cannot_act(({"type": cond_type},)):
        released = combat_grapple.release_from_grappler(state, cond_target.id)
        if released_from_grapple is not None:
            released_from_grapple.extend(released)
    return landed


def land_condition_on_participant(
    state,
    attacker: CombatParticipant,
    decl: "Declaration",
    cond_type: str,
    source: str,
    released_from_grapple: list[str] | None = None,
) -> bool:
    """Single-target landing rule for the combat producers (the spell path in _resolve_ability_packet
    and the non-spell ability path in _resolve_ability_condition_packet): land ``cond_type`` on
    ``decl.target_id`` (self when absent). Returns True iff it landed. Thin wrapper over
    ``_land_condition_on_one`` (M4.8 story-012 extraction); back-compat for existing callers."""
    return _land_condition_on_one(
        state, decl.target_id, attacker, cond_type, source, released_from_grapple=released_from_grapple
    )


def land_condition_on_participants(
    state, attacker: CombatParticipant, decl: "Declaration", cond_type: str, source: str
) -> list[str]:
    """Land ``cond_type`` on EACH participant of a multi-target declaration (M4.8 story-012).

    Resolves the target list: ``decl.target_ids`` (order-preserving dedup) when present, else the
    single ``decl.target_id``, else the caster (self-cast). The cap was already enforced at the
    declare-gate (combat_packet via spells.normalize_target_list); dedup here just prevents
    double-voicing the same ally. Returns the participant ids the buff actually LANDED on (an id not
    on the working state, or an immunity no-op, is dropped) — the subset the DM should name."""
    targets = resolve_effective_targets(decl.target_ids, decl.target_id, self_value=None, dedup=True)
    voiced: list[str] = []
    for tid in targets:
        if _land_condition_on_one(state, tid, attacker, cond_type, source):
            voiced.append(tid if tid is not None else attacker.id)
    return voiced
