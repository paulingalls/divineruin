"""Spend a held healing item and land HP in the caller's transaction."""

import json

from livekit.agents.llm import ToolError

import combat_spell_heal
import db
import db_content_queries
import db_mutations_inventory
import db_queries
import dice
import event_types as E
import inventory_refresh
from combat_down import is_terminally_down
from combat_events import EventSink, isolated_publish
from declarations import Declaration, DeclarationType, resolve_declaration
from game_events import publish_game_event
from item_effects import CONSUME_PREFIX, heal_profile
from session_data import SessionData
from tool_support import _validate_id


def is_consume(decl: Declaration) -> bool:
    return decl.type is DeclarationType.INTERACT and (decl.action or "").startswith(CONSUME_PREFIX)


async def _held_heal(holder_id, item_id, *, conn=None, queries=db_queries):
    _validate_id(item_id, "item_id")
    item = await db_content_queries.get_item(item_id, conn=conn)
    profile = heal_profile(item_id, item) if item is not None else None
    if profile is None or item is None:
        raise ToolError(f"{item_id!r} is not a healing item.")
    name = item["name"]
    slot = await queries.get_inventory_item(holder_id, item_id, conn=conn, for_update=conn is not None)
    if slot is None or slot["quantity"] <= 0:
        raise ToolError(f"{holder_id} has no untainted {name} to consume.")
    return name, profile


async def _combat_use(session, state, holder, decl, *, conn=None, queries=db_queries):
    if (
        holder is None
        or holder.type != "player"
        or holder.id not in session.party.member_ids
        or holder.is_fallen
        or is_terminally_down(holder)
    ):
        raise ToolError("Only a conscious party player can administer a healing item.")
    item_id = decl.action.removeprefix(CONSUME_PREFIX)
    name, profile = await _held_heal(holder.id, item_id, conn=conn, queries=queries)
    try:
        target = combat_spell_heal.combat_ally(state, decl.target_id or holder.id, name)
    except ValueError as error:
        raise ToolError(str(error)) from error
    return item_id, name, profile, target


async def preflight(session, state, declarations, *, conn=None, queries=db_queries):
    for actor_id, decl in declarations:
        if is_consume(decl):
            await _combat_use(session, state, state.get_participant(actor_id), decl, conn=conn, queries=queries)


async def preflight_declarations(session, state):
    await preflight(
        session,
        state,
        ((actor_id, resolve_declaration(raw)) for actor_id, raw in state.pending_declarations.items()),
    )


def _receipt(holder_id, item_id, name, remaining, healing_results) -> dict:
    packet = {
        "player_id": holder_id,
        "item_id": item_id,
        "item_name": name,
        "remaining_quantity": remaining,
        "healing_results": healing_results,
    }
    if item_id == "restoration_salve":
        packet["condition_removal"] = {"applied": False, "reason": "The salve has no condition selection rule."}
    return packet


async def resolve_combat(session, state, holder, decl, *, conn, sink: EventSink | None, queries):
    if conn is None or sink is None:
        raise RuntimeError("Combat item consumption requires a transaction and event buffer.")
    try:
        item_id, name, profile, target = await _combat_use(session, state, holder, decl, conn=conn, queries=queries)
    except ToolError as error:
        # Earlier packets may have already committed at a Fate pause.
        return {"actor_id": holder.id, "resolved": False, "reason": str(error)}
    remaining = await db_mutations_inventory.transact_inventory(holder.id, item_id, -1, conn=conn)
    results = await combat_spell_heal.land(profile, holder, [target], conn=conn)
    inventory = await inventory_refresh.inventory_payload(holder.id, conn=conn, queries=queries)
    await sink.emit(session.room, E.INVENTORY_UPDATED, inventory, event_bus=session.event_bus)
    return {
        "actor_id": holder.id,
        "resolved": True,
        "declaration_type": "interact",
        **_receipt(holder.id, item_id, name, remaining, results),
    }


async def consume_exploration(session: SessionData, item_id: str, target_id: str | None) -> str:
    holder_id = session.acting_player_id
    target_id = holder_id if target_id is None else target_id
    _validate_id(target_id, "target_id")
    async with session.combat_state_lock:
        if session.in_combat:
            raise ToolError("Declare a consume action with declare_phase while in combat.")
        if {holder_id, target_id} - set(session.party.member_ids):
            raise ToolError("Healing items require a party player at the holder's location.")
        async with db.transaction() as conn:
            rows = await db_queries.get_players_for_update([holder_id, target_id], conn=conn)
            holder, target = rows.get(holder_id), rows.get(target_id)
            if holder is None or target is None or holder["location_id"] != target["location_id"]:
                raise ToolError("Healing items require a party player at the holder's location.")
            name, profile = await _held_heal(holder_id, item_id, conn=conn)
            session.validate_acting_player(holder_id)
            remaining = await db_mutations_inventory.transact_inventory(holder_id, item_id, -1, conn=conn)
            results = await combat_spell_heal.land_exploration(
                profile, holder, {target_id: target}, conn=conn, dice_mod=dice
            )
            inventory = await inventory_refresh.inventory_payload(holder_id, conn=conn)

        hp = results[0]
        if hp["healed"] > 0:
            with isolated_publish("item heal HP"):
                await publish_game_event(
                    session.room,
                    E.HP_CHANGED,
                    {"current": hp["hp_current"], "max": hp["hp_max"]},
                    event_bus=session.event_bus,
                    destination_identities=[target_id],
                )
        with isolated_publish("item heal inventory"):
            await publish_game_event(session.room, E.INVENTORY_UPDATED, inventory, event_bus=session.event_bus)
        session.record_event(f"Used {name} on {target_id}, restoring {hp['healed']} HP")
    return json.dumps(_receipt(holder_id, item_id, name, remaining, results))
