"""Settle Sacrifice Play's payment before granting its attack rider."""

from __future__ import annotations

from typing import TYPE_CHECKING

import combat_damage
import combat_martial
import combat_order_riders
import dice
from combat_ability_gate import DeclaredAbility
from combat_damage_results import AutomaticDamageResult
from combat_fate_rolls import PacketRolls
from combat_order_riders import SACRIFICE_PLAY_NAME
from declarations import Declaration
from patron_synergy_combat import grant_marshal_rally
from session_data import CombatParticipant, CombatState, SessionData

if TYPE_CHECKING:
    from asyncpg import Connection

    from combat_events import EventSink


async def resolve(
    session: SessionData,
    state: CombatState,
    actor: CombatParticipant,
    decl: Declaration,
    resolved: DeclaredAbility,
    *,
    conn: Connection | None,
    sink: EventSink | None,
    progress: PacketRolls | None,
    queries,
    mutations,
    concentration_break_mod,
) -> dict:
    steps = progress.steps if progress is not None else {}
    receipt = steps.get("sacrifice_order")
    if receipt is None:
        allies, _ = combat_martial.order_recipients(state, actor, decl, resolved[0])
        recipient_id = allies[0]
        await combat_martial.pay(actor.id, resolved, queries=queries, conn=conn)
        rally = await grant_marshal_rally(state, actor.id, recipient_id, queries=queries, conn=conn)
        receipt = combat_martial.order_receipt(actor, decl, resolved, rally, effect_resolution="engine")
        notation = "2d6"
        receipt["payment"] = {"dice": notation, "raw_damage": dice.roll(notation).total, "recipient_id": recipient_id}
        steps["sacrifice_order"] = receipt

    payment = receipt["payment"]
    recipient = state.get_participant(payment["recipient_id"])
    assert recipient is not None
    # Attribute self-damage to the recipient so the marshal isn't recorded as an ally downer.
    landing = await combat_damage.apply_attack_result(
        session,
        recipient,
        {"name": SACRIFICE_PLAY_NAME},
        recipient,
        AutomaticDamageResult(payment["raw_damage"], "untyped", SACRIFICE_PLAY_NAME),
        recipient.ac,
        mutations=mutations,
        queries=queries,
        concentration_break_mod=concentration_break_mod,
        combat_state=state,
        conn=conn,
        sink=sink,
        publish_roll=False,
        progress=progress.scope("sacrifice_payment") if progress is not None else None,
    )
    if not landing:
        return {}
    payment["landing"] = landing
    receipt["order_rider_grant"] = combat_order_riders.grant_sacrifice_play(state, actor.id, recipient.id)
    return receipt
