import json
from typing import Annotated

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext
from pydantic import Field

import db
import db_content_queries
import db_mutations_inventory
import db_mutations_merchant
import db_queries
import event_types as E
import pricing_queries
import sale_pricing
from action_sound_content import ACTION_SOUND_EXPORTS, publish_action_sound
from db_errors import db_tool
from disposition import resolve_disposition
from game_events import publish_game_event
from inventory_refresh import publish_inventory
from merchant_purse import bind_sale_option, sale_terms
from session_data import SessionData
from tool_preconditions import require_npc_present
from tool_support import _validate_id

_REFUSAL = {
    "hostile": "This merchant is hostile and refuses to trade.",
    "quest_item": "Merchants won't buy quest items.",
    "wrong_type": "This merchant doesn't buy that type of item.",
    "wrong_rarity": "This merchant doesn't buy items of that rarity.",
    "no_value_base": "This item has no sale value.",
    "priced_to_zero": "This item is worth less than a silver.",
}


@function_tool()
@db_tool
async def sell_item(
    context: RunContext[SessionData],
    item_id: str,
    npc_id: str,
    quantity: Annotated[int, Field(strict=True)],
    offer_id: str = "",
) -> str:
    """Sell carried goods to a present merchant. Read offers aloud and wait for consent.
    Say what sold and how much silver was paid only for a completed sale.

    Args:
        item_id: The item ID from the acting player's inventory. Equipped, tainted and quest items cannot be sold.
        npc_id: The merchant ID from the present NPCs shared at trade entry.
        quantity: How many units the player agrees to sell. Must be at least one.
        offer_id: Empty for a new sale request. After consent, use the ID of the offered option.
    """
    _validate_id(item_id, "item_id")
    _validate_id(npc_id, "npc_id")
    if quantity < 1:
        raise ToolError("Sell at least one item.")
    context.disallow_interruptions()
    session = context.userdata
    player_id = session.acting_player_id
    await require_npc_present(session.location_id, npc_id, suffix=" to trade")

    async with db.transaction() as conn:
        npc = await db_content_queries.get_npc(npc_id, conn=conn)
        if npc is None:
            raise ToolError(f"Unknown merchant: {npc_id}")
        pool_id = npc["inventory_pool"]
        if pool_id is None:
            raise ToolError(f"{npc['name']} doesn't buy goods.")
        pools = await sale_pricing.get_inventory_pools(conn=conn)
        item = await db_content_queries.get_item(item_id, conn=conn)
        if item is None:
            raise ToolError(f"'{item_id}' has no catalog sale value.")

        pool = pools[pool_id]
        pricing = await pricing_queries.get_economy_pricing(conn=conn)
        location = await db_content_queries.get_location(pool["location"], conn=conn)
        allocation = sale_pricing.merchant_gold_allocation(pool, location, pricing)
        merchant = await db_mutations_merchant.lock_merchant(npc_id, allocation, conn=conn)
        revision = await conn.fetchval(
            "SELECT inventory_revision FROM players WHERE player_id = $1 FOR UPDATE", player_id
        )
        if revision is None:
            raise ToolError(f"Unknown player: {player_id}")

        stack = await db_queries.get_inventory_item(player_id, item_id, conn=conn, for_update=True)
        if stack is None:
            if await db_queries.get_inventory_item(player_id, item_id, conn=conn, tainted=True) is not None:
                raise ToolError(f"Merchants won't buy tainted {item['name']}.")
            raise ToolError(f"You aren't carrying {item['name']}.")
        if quantity > stack["quantity"]:
            raise ToolError(f"You only carry {stack['quantity']} available to sell.")
        if stack.get("equipped", False):
            raise ToolError(f"{item['name']} is equipped. Unequip it before selling.")

        disposition = await resolve_disposition(
            npc_id, player_id, conn=conn, default_disposition=npc.get("default_disposition", "neutral")
        )
        quote = sale_pricing.quote_sale(item, pricing, kind="merchant", disposition=disposition, pool=pool, pools=pools)
        if not quote["available"]:
            reason = _REFUSAL[quote["reason"]]
            if buyer := quote["merchant_kind"]:
                reason += f" Try a {buyer}."
            raise ToolError(reason)

        unit_sp = quote["price_sp"]
        terms, refusal = sale_terms(merchant, item, item_id, quantity, unit_sp, disposition)
        session.validate_acting_player(player_id)
        if refusal:
            return json.dumps({"status": "refused", **refusal})
        if not offer_id and terms[0][0] == "full":
            total_sp = terms[0][1]
        else:
            quote_state = (
                npc_id,
                player_id,
                item_id,
                merchant["last_restock_day"],
                unit_sp,
                revision,
            )
            options = [bind_sale_option(kind, total, quantity, quote_state) for kind, total in terms]
            chosen = next((option for option in options if option["offer_id"] == offer_id), None)
            if chosen is None or chosen["kind"] == "consignment":
                response = {
                    "status": "offer",
                    "item_id": item_id,
                    "npc_id": npc_id,
                    "quantity": quantity,
                    "quoted_total_price_sp": unit_sp * quantity,
                    "options": options,
                }
                if chosen is not None:
                    response["reason"] = "I can't take consignments yet."
                elif offer_id:
                    response["reason"] = "That offer has changed. Ask about the current offer."
                return json.dumps(response)
            total_sp = chosen["total_price_sp"]
        gold = total_sp / pricing["silver_per_gold"]
        await db_mutations_merchant.debit_merchant(npc_id, merchant, item_id, quantity, total_sp, conn=conn)
        await db_mutations_inventory.transact_inventory(player_id, item_id, -quantity, conn=conn)
        balance = await db_mutations_inventory.credit_player_gold(player_id, gold, conn=conn)

    await publish_game_event(
        session.room,
        E.CURRENCY_GAINED,
        {"player_id": player_id, "amount": gold, "currency": "gold", "source": "sale", "new_balance": balance},
        event_bus=session.event_bus,
    )
    await publish_inventory(session, player_id)
    await publish_action_sound(session, ACTION_SOUND_EXPORTS["ACTION_SELL_ITEM"])
    return json.dumps(
        {
            "status": "sold",
            "item_id": item_id,
            "npc_id": npc_id,
            "quantity": quantity,
            "unit_price_sp": total_sp // quantity if total_sp % quantity == 0 else None,
            "total_price_sp": total_sp,
        }
    )
