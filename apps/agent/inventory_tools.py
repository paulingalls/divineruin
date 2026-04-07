"""Inventory tools — add and remove items."""

import json
import logging

from livekit.agents.llm import function_tool
from livekit.agents.voice import RunContext

import db
import db_content_queries
import db_mutations
import db_queries
import event_types as E
from db_errors import db_tool
from game_events import publish_game_event
from session_data import SessionData
from tool_support import _cap_str

logger = logging.getLogger("divineruin.tools")


@function_tool()
@db_tool
async def add_to_inventory(
    context: RunContext[SessionData],
    item_id: str,
    quantity: int,
    source: str,
) -> str:
    """Add an item to the player's inventory. Provide the item ID, quantity,
    and source (e.g. 'looted from goblin', 'purchased from merchant',
    'quest reward')."""
    return await _add_to_inventory_impl(context, item_id, quantity, source)


async def _add_to_inventory_impl(
    context: RunContext[SessionData],
    item_id: str,
    quantity: int,
    source: str,
    *,
    db_mod=db,
    mutations=db_mutations,
    queries=db_queries,
    content=db_content_queries,
) -> str:
    logger.info("add_to_inventory called: item_id=%s, quantity=%d, source=%s", item_id, quantity, source)
    cap_err = _cap_str(source, 256, "source")
    if cap_err:
        return cap_err
    if quantity < 1 or quantity > 99:
        return json.dumps({"error": "Quantity must be between 1 and 99."})
    session: SessionData = context.userdata

    item = await content.get_item(item_id)
    if item is None:
        return json.dumps({"error": f"Item '{item_id}' not found."})

    item_name = item.get("name", item_id)

    async with db_mod.transaction() as conn:
        await mutations.add_inventory_item(session.player_id, item_id, quantity, conn=conn)

    full_inventory = await queries.get_player_inventory(session.player_id)

    await publish_game_event(
        session.room,
        E.INVENTORY_UPDATED,
        {"inventory": full_inventory},
        event_bus=session.event_bus,
    )

    image_url = db_mod._compute_item_image_url(item)
    acquired_payload: dict = {
        "name": item_name,
        "description": item.get("description", ""),
        "rarity": item.get("rarity", "common"),
    }
    if image_url:
        acquired_payload["image_url"] = image_url
    await publish_game_event(
        session.room,
        E.ITEM_ACQUIRED,
        acquired_payload,
        event_bus=session.event_bus,
    )

    session.record_event(f"Added {quantity}x {item_name} ({source})")
    session.record_companion_memory(f"Found {item_name}")
    session.session_items_found.append(item_name)

    response = {
        "action": "added",
        "item_id": item_id,
        "item_name": item_name,
        "quantity": quantity,
        "source": source,
    }
    logger.info("add_to_inventory result: +%d %s from %s", quantity, item_id, source)
    return json.dumps(response)


@function_tool()
@db_tool
async def remove_from_inventory(
    context: RunContext[SessionData],
    item_id: str,
) -> str:
    """Remove an item from the player's inventory. Use when an item is
    consumed, sold, or destroyed."""
    return await _remove_from_inventory_impl(context, item_id)


async def _remove_from_inventory_impl(
    context: RunContext[SessionData],
    item_id: str,
    *,
    db_mod=db,
    mutations=db_mutations,
    queries=db_queries,
    content=db_content_queries,
) -> str:
    logger.info("remove_from_inventory called: item_id=%s", item_id)
    session: SessionData = context.userdata

    item = await content.get_item(item_id)
    item_name = item.get("name", item_id) if item else item_id

    pending_events: list[tuple[str, dict]] = []

    async with db_mod.transaction() as conn:
        slot = await queries.get_inventory_item(session.player_id, item_id, conn=conn, for_update=True)
        if slot is None:
            return json.dumps({"error": f"Item '{item_id}' not in inventory."})

        if slot.get("equipped", False):
            return json.dumps({"error": f"Item '{item_id}' is equipped. Unequip it first."})

        await mutations.remove_inventory_item(session.player_id, item_id, conn=conn)

        pending_events.append(
            (
                E.INVENTORY_UPDATED,
                {
                    "action": "removed",
                    "item_id": item_id,
                    "item_name": item_name,
                    "quantity": 0,
                },
            )
        )

    for event_type, payload in pending_events:
        await publish_game_event(session.room, event_type, payload, event_bus=session.event_bus)

    session.record_event(f"Removed {item_name}")

    response = {
        "action": "removed",
        "item_id": item_id,
        "item_name": item_name,
    }
    logger.info("remove_from_inventory result: removed %s", item_id)
    return json.dumps(response)
