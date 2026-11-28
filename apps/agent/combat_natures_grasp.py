"""Settle Nature's Grasp against the mover and clear it at that mover's turn end."""

import combat_spell_condition
import spells
from combat_fate_rolls import PacketRolls, PhaseRolls, saved_throw
from reaction_catalog import NATURES_GRASP
from session_data import CombatParticipant, CombatState, SessionData


async def settle(
    session: SessionData,
    state: CombatState,
    mover: CombatParticipant,
    spend: dict,
    deps: dict,
    fate_rolls: PhaseRolls | None,
) -> dict | None:
    caster_id = spend["actor_id"]
    receipt = {
        "ability_id": NATURES_GRASP,
        "actor_id": caster_id,
        "target_id": mover.id,
        "held_seq": spend["held_seq"],
        "window_id": spend["window_id"],
        "stage": spend["stage"],
    }
    if not session.party.contains(caster_id):
        if fate_rolls is not None:
            fate_rolls.kept = None
        return {**receipt, "resolved": False, "reason": "Nature's Grasp caster is unavailable."}
    caster = state.get_participant(caster_id)
    assert caster is not None
    progress = None
    if fate_rolls is not None:
        progress = PacketRolls(fate_rolls, spend.setdefault("steps", {}), deps["queries"], deps["conn"])
        if "save" in progress.steps and fate_rolls.kept is None:
            saved = saved_throw(progress.steps["save"])
            d20 = saved.d20
            assert d20 is not None
            if await fate_rolls.hold(
                session, "save", mover.id, d20.evaluate(saved.roll), d20, queries=deps["queries"], conn=deps["conn"]
            ):
                return None
    await combat_spell_condition.land_natures_grasp(
        session,
        state,
        caster,
        mover,
        spells.get_spell(NATURES_GRASP),
        receipt,
        cast_packet=spend["cast_packet"],
        progress=progress,
        conn=deps["conn"],
    )
    if progress is not None and progress.paused:
        return None
    receipt["resolved"] = "condition_inflicted" in receipt
    return receipt


def finish_held(state: CombatState) -> None:
    head = state.held_actions.pop(0)
    actor_id = head["actor_id"]
    if state.held_actions and state.held_actions[0]["actor_id"] == actor_id:
        return
    if (mover := state.get_participant(actor_id)) is not None:
        mover.conditions = [effect for effect in mover.conditions if effect.get("source") != NATURES_GRASP]
