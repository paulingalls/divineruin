"""Resolve Turn Undead/Hollow's creature saves and effects in the cast transaction."""

from functools import partial

import check_resolution_save
import combat_damage
import combat_spatial as spatial
import conditions
import db_queries
import encounter_facts
import still_encounter
from architect_reaction import Interception
from combat_condition_landing import _land_condition_on_one
from combat_fate_rolls import PacketRolls, packet_save
from combat_legendary_resistance import finalize_save, override_fields
from combat_spell_damage import spell_save_dc
from combat_spell_recipients import caster_radius_refusal
from session_data import CombatParticipant, CombatState, SessionData
from spells import Spell

TURN_UNDEAD = "divine_turn_undead_hollow"
_RADIUS_FT = 30
_DURATION_ROUNDS = 10


def select(state: CombatState, caster: CombatParticipant) -> tuple[list[dict], dict[str, str]]:
    placement = spatial.require_spatial(state)
    protected = still_encounter.protected_ids(state)
    selected = []
    refused = {}
    for target in state.participants:
        if target.id == caster.id:
            continue
        if target.type in ("player", "temporary_hollowed", "structure"):
            reason = "Target category cannot be turned."
        elif (
            state.choir_encounter
            and target.id == state.choir_encounter["owner_id"]
            and (state.choir_encounter["phase"] != "exposed")
        ):
            reason = "The Choir's core is hidden."
        else:
            reason = caster_radius_refusal(
                state, placement, caster.id, target, _RADIUS_FT, protected, undead_hollow=True
            )
        if reason:
            refused[target.id] = reason
        else:
            selected.append({"target_id": target.id})
    return selected, refused


async def _resolve_target(
    session: SessionData,
    state: CombatState,
    caster: CombatParticipant,
    target: CombatParticipant,
    spell: Spell,
    dc: int,
    progress: PacketRolls | None,
    *,
    queries,
    conn,
    sink,
) -> dict | None:
    save = await packet_save(
        progress,
        session,
        target.id,
        spell.name,
        partial(
            check_resolution_save.roll_participant_save,
            target,
            "wisdom",
            dc,
            spell.name,
            originating_participant_id=caster.id,
            combat_state=state,
        ),
        state=state,
    )
    if save is None:
        return None
    target.conditions = conditions.remove_conditions(target.conditions, save.consumed_conditions)
    destroys = caster.level >= 5 and target.hp_current < 5 * caster.level
    save = finalize_save(
        state,
        target,
        save,
        failed_damage=target.hp_current if destroys else 0,
        failed_conditions=() if destroys else ("frightened",),
    )
    result = {
        "save": {
            "attribute": save.save_type,
            "roll": save.roll,
            "total": save.total,
            "dc": save.dc,
            "success": save.success,
            **override_fields(save),
            **encounter_facts.rally_receipt(target.id, save.rally_sources),
        }
    }
    if save.success:
        return {**result, "outcome": "unaffected", "reason": "Succeeded on its Wisdom save."}
    if destroys:
        death = await combat_damage.destroy_creature(session, state, target, queries=queries, conn=conn, sink=sink)
        return {**result, **death, "outcome": "destroyed"}
    previous = next((c.get("turn_undead") for c in target.conditions if c["type"] == "frightened"), None)
    landed = _land_condition_on_one(
        state,
        target.id,
        caster,
        "frightened",
        source=caster.id,
        packet=result,
        duration=_DURATION_ROUNDS,
    )
    if not landed:
        return {**result, "outcome": "unaffected", "reason": "Immune to Frightened."}
    condition = next(c for c in target.conditions if c["type"] == "frightened")
    state.ac_modifiers.pop(target.id, None)
    condition["turn_undead"] = previous if previous is not None else {}
    return {
        **result,
        "outcome": "frightened",
        "source_id": caster.id,
        "duration_rounds": _DURATION_ROUNDS,
        "reason": "Declare this creature's turns as usual. It flees from the caster while Frightened.",
    }


async def land(
    session: SessionData,
    state: CombatState,
    caster: CombatParticipant,
    spell: Spell,
    packet: dict,
    selected: list[dict],
    refused: dict[str, str],
    redirects: dict,
    delivered: list[dict],
    interception: Interception | None,
    *,
    progress: PacketRolls | None,
    conn,
    queries=db_queries,
    sink=None,
) -> None:
    dc = spell_save_dc(caster, "wisdom", packet)
    receipts = progress.steps.setdefault("receipts", {}) if progress is not None else {}
    active = {row["target_id"] for row in delivered}
    absorbed = {row["target_id"] for row in packet.get("absorbed", [])}
    recipient_ids = (*refused, *(entry["target_id"] for entry in selected))
    for target_id in recipient_ids:
        if target_id in receipts:
            continue
        target = state.get_participant(target_id)
        if target is None:
            raise RuntimeError(f"Missing Turn Undead/Hollow recipient {target_id}")
        reason = refused.get(target_id)
        if target_id in redirects and redirects[target_id] != target_id:
            reason = "Harmonic Shield redirected the spell."
        elif interception is not None and target_id == interception["target_id"]:
            reason = "Reactive Architecture blocked the spell."
        elif target_id in absorbed:
            reason = "Absorb Magic stopped the spell."
        if reason is not None:
            result = {"outcome": "unaffected", "reason": reason}
        else:
            if target_id not in active:
                raise RuntimeError(f"Missing Turn Undead/Hollow delivery for {target_id}")
            result = await _resolve_target(
                session,
                state,
                caster,
                target,
                spell,
                dc,
                progress.scope(target_id) if progress is not None else None,
                queries=queries,
                conn=conn,
                sink=sink,
            )
            if result is None:
                return
        receipts[target_id] = {"target_id": target_id, "target": target.name, **result}
    packet["turn_undead_dc"] = dc
    packet["turn_undead"] = [receipts[target_id] for target_id in recipient_ids]
    packet["effect"] = "Use the Turn Undead/Hollow outcomes to narrate each creature's response."
    packet["narration_cue"] = "Your holy symbol rings with divine power."
