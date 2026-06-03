"""Inventory tool — the ``transact`` verb (signed-delta goods exchange).

transact(item_id, delta, source) folds the legacy add_to_inventory /
remove_from_inventory tools into one verb (M5, ADR 0007): a positive delta gains
items, a negative delta loses them. The gain path mirrors the old add behaviour
(content existence check, INVENTORY_UPDATED + ITEM_ACQUIRED, session bookkeeping);
the loss path keeps the equipped/existence guards and now decrements by magnitude
(quantity-aware) via db_mutations_inventory.transact_inventory instead of always
deleting the whole stack.
"""

import json
import logging

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import db
import db_content_queries
import db_mutations
import db_mutations_inventory
import db_queries
import event_types as E
from db_errors import db_tool
from game_events import publish_game_event
from session_data import SessionData
from tool_support import _cap_str, _validate_id

logger = logging.getLogger("divineruin.tools")

_MAX_MAGNITUDE = 99


@function_tool()
@db_tool
async def transact(
    context: RunContext[SessionData],
    item_id: str,
    delta: int,
    source: str = "",
) -> str:
    """Physical goods change hands. Pass a signed delta: a positive number to
    GAIN that many of an item (looted, bought, quest reward), a negative number
    to LOSE/SPEND/CONSUME them (sold, used, destroyed). Optionally give a source
    for gains, e.g. 'looted from goblin'."""
    return await _transact_impl(context, item_id, delta, source)


async def _transact_impl(
    context: RunContext[SessionData],
    item_id: str,
    delta: int,
    source: str = "",
    *,
    db_mod=db,
    mutations=db_mutations,
    inventory_mutations=db_mutations_inventory,
    queries=db_queries,
    content=db_content_queries,
) -> str:
    # item_id is external (DM voice tool-call) — validate at the boundary.
    _validate_id(item_id, "item_id")
    _cap_str(source, 256, "source")
    if delta == 0:
        raise ToolError("delta must be non-zero — positive gains items, negative loses them.")
    if abs(delta) > _MAX_MAGNITUDE:
        raise ToolError(f"Quantity magnitude must be between 1 and {_MAX_MAGNITUDE}.")

    logger.info("transact called: item_id=%s, delta=%d, source=%s", item_id, delta, source)
    session: SessionData = context.userdata
    item = await content.get_item(item_id)

    if delta > 0:
        return await _gain(session, item_id, delta, source, item, db_mod=db_mod, mutations=mutations, queries=queries)
    return await _lose(
        session, item_id, delta, item, db_mod=db_mod, inventory_mutations=inventory_mutations, queries=queries
    )


async def _gain(session, item_id, delta, source, item, *, db_mod, mutations, queries) -> str:
    if item is None:
        raise ToolError(f"Item '{item_id}' not found.")
    item_name = item.get("name", item_id)

    async with db_mod.transaction() as conn:
        await mutations.add_inventory_item(session.player_id, item_id, delta, conn=conn)

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

    suffix = f" ({source})" if source else ""
    session.record_event(f"Gained {delta}x {item_name}{suffix}")
    session.record_companion_memory(f"Found {item_name}")
    session.session_items_found.append(item_name)

    logger.info("transact result: +%d %s (%s)", delta, item_id, source)
    return json.dumps(
        {"action": "added", "item_id": item_id, "item_name": item_name, "quantity": delta, "source": source}
    )


async def _lose(session, item_id, delta, item, *, db_mod, inventory_mutations, queries) -> str:
    item_name = item.get("name", item_id) if item else item_id
    magnitude = -delta
    pending_events: list[tuple[str, dict]] = []

    async with db_mod.transaction() as conn:
        slot = await queries.get_inventory_item(session.player_id, item_id, conn=conn, for_update=True)
        if slot is None:
            raise ToolError(f"Item '{item_id}' not in inventory.")
        if slot.get("equipped", False):
            raise ToolError(f"Item '{item_id}' is equipped. Unequip it first.")

        remaining = await inventory_mutations.transact_inventory(session.player_id, item_id, delta, conn=conn)
        pending_events.append(
            (
                E.INVENTORY_UPDATED,
                {
                    "action": "removed",
                    "item_id": item_id,
                    "item_name": item_name,
                    "quantity": max(remaining, 0),
                },
            )
        )

    for event_type, payload in pending_events:
        await publish_game_event(session.room, event_type, payload, event_bus=session.event_bus)

    session.record_event(f"Lost {magnitude}x {item_name}")

    logger.info("transact result: -%d %s", magnitude, item_id)
    return json.dumps({"action": "removed", "item_id": item_id, "item_name": item_name, "quantity": max(remaining, 0)})
