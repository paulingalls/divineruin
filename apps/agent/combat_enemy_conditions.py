"""Settle conditions attached to enemy actions."""

from types import SimpleNamespace

from combat_condition_landing import _land_condition_on_one
from combat_enemy_active import already_hollowed
from condition_restrictions import cannot_act
from declarations import Declaration
from session_data import CombatParticipant, SessionData


async def _apply_condition_result(
    session: SessionData,
    attacker: CombatParticipant,
    target: CombatParticipant,
    decl: "Declaration",
    cond_type: str,
    result,
    summary: dict,
    *,
    state,
    conn,
    concentration_break_mod,
    duration=None,
) -> None:
    if result.success:
        summary["condition_resisted"] = cond_type
        return
    if already_hollowed(target, cond_type):
        return
    if _land_condition_on_one(
        state,
        target.id,
        attacker,
        cond_type,
        source=decl.action or "",
        packet=summary,
        duration=duration,
    ):
        summary["condition_inflicted"] = cond_type
        if target.type == "player" and cond_type in cannot_act(target.conditions):
            broken = await concentration_break_mod.break_concentration_on_incapacitation(
                session, target.id, combat_state=state, conn=conn
            )
            if broken is not None:
                summary["concentration_broken"] = broken
        return
    summary["condition_immune"] = cond_type
    if item_immunity := target.condition_immunities.get(cond_type):
        summary["condition_immunity_source"] = item_immunity
    if cond_type == "prone" and target.prone_immunity:
        summary["prone_immunity"] = target.prone_immunity


async def land_outcome(session, attacker, target, decl, action, result, summary, **kwargs):
    if "resolution" not in action:
        return await _apply_condition_result(
            session, attacker, target, decl, action["applies_condition"], result, summary, **kwargs
        )
    branch = "conditions_on_success" if result.success else "conditions_on_failure"
    summary["conditions_inflicted"] = []
    for rider in action[branch]:
        await _apply_condition_result(
            session,
            attacker,
            target,
            decl,
            rider["applies_condition"],
            SimpleNamespace(success=False),
            summary,
            **{**kwargs, "duration": rider["duration"]},
        )
        if summary.get("condition_inflicted") == rider["applies_condition"]:
            summary["conditions_inflicted"].append(rider["applies_condition"])
