"""Settle the item attached to a completed Field Medic attack."""

from typing import TYPE_CHECKING

import combat_order_riders
import item_heal

if TYPE_CHECKING:
    from combat_events import EventSink
    from combat_phase import ResolutionPacket
    from combat_state import CombatState
    from session_data import SessionData


async def settle(
    session: "SessionData",
    state: "CombatState",
    packet: "ResolutionPacket",
    summary: dict,
    *,
    conn,
    sink: "EventSink",
    queries,
) -> None:
    item = packet.declaration.healing_item
    if item is None:
        return
    holder = state.get_participant(packet.actor_id)
    rider = combat_order_riders.select_field_medic(state, packet.actor_id)
    if holder is None or rider is None:
        raise RuntimeError(f"Combined declaration for {packet.actor_id} lost its holder or Field Medic Order.")
    heal = await item_heal.resolve_combat(
        session, state, holder, item_heal.attached_consume(item), conn=conn, sink=sink, queries=queries
    )
    combat_order_riders.consume(state, holder.id, rider)
    summary.setdefault("declaration_type", "attack")
    summary.setdefault("action", packet.declaration.action)
    summary["effect_resolution"] = "engine"
    summary["field_medic"] = {
        "order_id": rider["order_id"],
        "name": combat_order_riders.FIELD_MEDIC_NAME,
        "source_id": rider["source_id"],
        "heal": {"item_id": item["item_id"], **heal},
    }
