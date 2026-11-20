import combat_grapple
import condition_voice_rules
import conditions
from combat_participant import CombatParticipant
from condition_catalog import CONDITION_CATALOG
from condition_restrictions import cannot_act


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
