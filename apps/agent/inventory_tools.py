"""Exchange inventory quantities and equip owned gear."""

import json
import logging
from typing import Literal

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import db
import db_content_queries
import db_mutations
import db_mutations_inventory
import db_queries
import equipment_tools
import event_types as E
from asset_utils import compute_item_image_url
from db_errors import db_tool
from game_events import publish_game_event
from inventory_refresh import publish_inventory
from session_data import SessionData
from tool_support import _cap_str, _validate_id, build_item_acquired_payload

logger = logging.getLogger("divineruin.tools")

_MAX_MAGNITUDE = 99


@function_tool()
@db_tool
async def transact(
    context: RunContext[SessionData],
    item_id: str,
    delta: int,
    action: Literal["exchange", "equip"],
    source: str = "",
) -> str:
    """Exchange physical goods using a positive delta for gains or a negative delta for losses.
    Use equip with delta=0 to wear an owned weapon, armor or shield outside combat. Narrate the change.
    To heal, use the item's consume_id with activate or declare a consume action in combat.
    Source is optional for gains."""
    return await _transact_impl(context, item_id, delta, source, action=action)


async def _transact_impl(
    context: RunContext[SessionData],
    item_id: str,
    delta: int,
    source: str = "",
    *,
    action: Literal["exchange", "equip"] = "exchange",
    db_mod=db,
    mutations=db_mutations,
    inventory_mutations=db_mutations_inventory,
    queries=db_queries,
    content=db_content_queries,
) -> str:
    # item_id is external (DM voice tool-call) — validate at the boundary.
    _validate_id(item_id, "item_id")
    _cap_str(source, 256, "source")
    if action == "equip":
        if delta != 0:
            raise ToolError("Use delta=0 to equip gear.")
        context.disallow_interruptions()
        return await equipment_tools.equip(
            context.userdata,
            item_id,
            await content.get_item(item_id),
            db_mod=db_mod,
            queries=queries,
            inventory_mutations=inventory_mutations,
        )
    if delta == 0:
        raise ToolError("delta must be non-zero — positive gains items, negative loses them.")
    if abs(delta) > _MAX_MAGNITUDE:
        raise ToolError(f"Quantity magnitude must be between 1 and {_MAX_MAGNITUDE}.")

    logger.info("transact called: item_id=%s, delta=%d, source=%s", item_id, delta, source)
    session: SessionData = context.userdata
    player_id = session.acting_player_id
    item = await content.get_item(item_id)

    if delta > 0:
        return await _gain(
            session, player_id, item_id, delta, source, item, db_mod=db_mod, mutations=mutations, queries=queries
        )
    return await _lose(
        session,
        player_id,
        item_id,
        delta,
        item,
        db_mod=db_mod,
        inventory_mutations=inventory_mutations,
        queries=queries,
    )


async def _gain(session, player_id, item_id, delta, source, item, *, db_mod, mutations, queries) -> str:
    if item is None:
        raise ToolError(f"Item '{item_id}' not found.")
    item_name = item.get("name", item_id)

    async with db_mod.transaction() as conn:
        session.validate_acting_player(player_id)
        await mutations.add_inventory_item(player_id, item_id, delta, tainted=False, conn=conn)

    # ONE builder for every ITEM_ACQUIRED writer (tool_support): the combat-loot pass emits the
    # same shape from the same place, so the client's item card can never go blank on one path
    # while rendering on the other.
    acquired_payload = build_item_acquired_payload(
        item,
        item_id=item_id,
        image_url=compute_item_image_url(item),
        quantity=delta,
        source=source,
        player_id=player_id,
    )
    await publish_game_event(
        session.room,
        E.ITEM_ACQUIRED,
        acquired_payload,
        event_bus=session.event_bus,
    )

    await publish_inventory(session, player_id, queries=queries)

    suffix = f" ({source})" if source else ""
    session.record_event(f"Gained {delta}x {item_name}{suffix}")
    session.record_companion_memory(f"Found {item_name}")
    session.record_item_found(player_id, item_name)

    logger.info("transact result: +%d %s (%s)", delta, item_id, source)
    return json.dumps(
        {"action": "added", "item_id": item_id, "item_name": item_name, "quantity": delta, "source": source}
    )


async def _lose(session, player_id, item_id, delta, item, *, db_mod, inventory_mutations, queries) -> str:
    item_name = item.get("name", item_id) if item else item_id
    magnitude = -delta

    async with db_mod.transaction() as conn:
        slot = await queries.get_inventory_item(player_id, item_id, conn=conn, for_update=True)
        if slot is None:
            raise ToolError(f"Item '{item_id}' not in inventory.")
        if slot.get("equipped", False):
            raise ToolError(f"Item '{item_id}' is equipped. Unequip it first.")

        session.validate_acting_player(player_id)
        remaining = await inventory_mutations.transact_inventory(player_id, item_id, delta, conn=conn)

    await publish_inventory(session, player_id, queries=queries)

    session.record_event(f"Lost {magnitude}x {item_name}")

    logger.info("transact result: -%d %s", magnitude, item_id)
    return json.dumps({"action": "removed", "item_id": item_id, "item_name": item_name, "quantity": max(remaining, 0)})
