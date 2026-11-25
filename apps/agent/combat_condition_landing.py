from typing import TYPE_CHECKING

import combat_grapple
import condition_voice_rules
import conditions
from combat_participant import CombatParticipant
from condition_catalog import CONDITION_CATALOG
from condition_produce import resolve_effective_targets
from condition_restrictions import cannot_act

if TYPE_CHECKING:
    from declarations import Declaration


def can_land_condition(state, target: CombatParticipant, cond_type: str) -> bool:
    return not (
        cond_type in target.condition_immunities
        or (cond_type == "prone" and target.prone_immunity)
        or any(cond_type in CONDITION_CATALOG[condition["type"]].immunities for condition in target.conditions)
        or (
            cond_type == "inspired"
            and condition_voice_rules.no_spoken_buffs(target.conditions, state=state, actor_id=target.id)
        )
    )


def _land_condition_on_one(
    state,
    target_id: str | None,
    attacker: CombatParticipant,
    cond_type: str,
    source: str,
    *,
    packet: dict,
    duration: int | None = None,
    inspire_attack_upgrade: bool = False,
) -> bool:
    """Land a condition (beneficial or hostile) on ONE in-combat participant (M4.8; M13 story-002
    adds the hostile caller). Self-target (``target_id`` None) falls back to the caster; a given id
    is looked up on the working ``state``. Returns True iff it actually landed (``has_condition``) —
    a target not on the state, or an immunity no-op, returns False so the caller drops the signal.
    Grapples released by a disabling condition are reported on ``packet``. The mutation rides
    save_combat_state."""
    cond_target = attacker if target_id is None else state.get_participant(target_id)
    if cond_target is None or not can_land_condition(state, cond_target, cond_type):
        return False
    spec = conditions.CONDITION_CATALOG.get(cond_type)
    cond_target.conditions = conditions.apply_condition(
        cond_target.conditions,
        cond_type,
        source=attacker.id if cond_type == "charmed" else source,
        duration=duration,
        inspire_attack_upgrade=inspire_attack_upgrade,
        originating_participant_id=attacker.id if spec is not None and spec.tick_save is not None else None,
    )
    if duration is not None and not attacker.is_ally and attacker.type == "enemy":
        for condition in cond_target.conditions:
            if condition["type"] == cond_type:
                condition["inflicted_round"] = state.round_number
    landed = conditions.has_condition(cond_target.conditions, cond_type)
    if landed and cond_type in cannot_act(cond_target.conditions):
        released = combat_grapple.release_from_grappler(state, cond_target.id)
        if released:
            packet.setdefault("released_from_grapple", []).extend(released)
    return landed


def land_condition_on_participant(
    state,
    attacker: CombatParticipant,
    decl: "Declaration",
    cond_type: str,
    source: str,
    *,
    packet: dict,
    inspire_attack_upgrade: bool = False,
) -> bool:
    """Single-target landing rule for the combat producers (the spell path in _resolve_ability_packet
    and the non-spell ability path in _resolve_ability_condition_packet): land ``cond_type`` on
    ``decl.target_id`` (self when absent). Returns True iff it landed. Thin wrapper over
    ``_land_condition_on_one``; ``packet`` receives any release caused by the condition."""
    return _land_condition_on_one(
        state, decl.target_id, attacker, cond_type, source, packet=packet, inspire_attack_upgrade=inspire_attack_upgrade
    )


def land_condition_on_participants(
    state,
    attacker: CombatParticipant,
    decl: "Declaration",
    cond_type: str,
    source: str,
    *,
    packet: dict,
    inspire_attack_upgrade: bool = False,
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
        if _land_condition_on_one(
            state, target_id, attacker, cond_type, source, packet=packet, inspire_attack_upgrade=inspire_attack_upgrade
        ):
            voiced.append(target_id if target_id is not None else attacker.id)
    return voiced
