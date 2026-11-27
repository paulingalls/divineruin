from typing import Annotated

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext
from pydantic import Field

import db_content_queries
import db_mutations_inventory
import db_mutations_merchant
import db_queries
import sale_pricing
from action_sound_content import ACTION_SOUND_EXPORTS, publish_action_sound
from consignment import OFFER_PREFIX, expires_on, place
from db_errors import db_tool
from disposition import resolve_disposition
from durability import max_hits
from merchant_purse import bind_sale_option, sale_terms
from merchant_tools import merchant_visit, receipt
from session_data import SessionData
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
    if quantity < 1:
        raise ToolError("Sell at least one item.")
    async with merchant_visit(context, npc_id) as visit:
        conn = visit.conn
        player_id = visit.player_id
        merchant = visit.merchant
        item = await db_content_queries.get_item(item_id, conn=conn)
        if item is None:
            raise ToolError(f"'{item_id}' has no catalog sale value.")

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
            npc_id, player_id, conn=conn, default_disposition=visit.npc.get("default_disposition", "neutral")
        )
        quote = sale_pricing.quote_sale(
            item, visit.pricing, kind="merchant", disposition=disposition, pool=visit.pool, pools=visit.pools
        )
        if not quote["available"]:
            reason = _REFUSAL[quote["reason"]]
            if buyer := quote["merchant_kind"]:
                reason += f" Try a {buyer}."
            raise ToolError(reason)

        unit_sp = quote["price_sp"]
        terms, refusal = sale_terms(merchant.state, item, item_id, quantity, unit_sp, disposition)
        if any(kind == "consignment" for kind, _ in terms):
            hits = stack.get("current_hits")
            tier = item.get("durability_tier")
            if tier and hits is not None and hits < max_hits(tier):
                terms = [(kind, total) for kind, total in terms if kind != "consignment"]
                refusal = {"reason": f"{item['name']} is damaged. Please get it mended first."}
        if offer_id.startswith(OFFER_PREFIX) and not any(kind == "consignment" for kind, _ in terms):
            raise ToolError(refusal.get("reason", "That item is no longer eligible for consignment."))
        if not terms:
            return receipt(visit, {"status": "refused", **refusal})

        if not offer_id and terms[0][0] == "full":
            total_sp = terms[0][1]
        else:
            quote_state = (npc_id, player_id, item_id, merchant.today, unit_sp, merchant.revision)
            options = [bind_sale_option(kind, total, quantity, quote_state) for kind, total in terms]
            chosen = next((option for option in options if option["offer_id"] == offer_id), None)
            if chosen is None:
                response = {
                    "status": "offer",
                    "item_id": item_id,
                    "npc_id": npc_id,
                    "quantity": quantity,
                    "quoted_total_price_sp": unit_sp * quantity,
                    "options": options,
                }
                if offer_id:
                    response["reason"] = "That offer has changed. Ask about the current offer."
                elif refusal:
                    response.update(refusal)
                return receipt(visit, response)
            total_sp = chosen["total_price_sp"]
            if chosen["kind"] == "consignment":
                entry = place(player_id, item_id, quantity, total_sp, merchant.today)
                merchant.state["consigned_items"].append(entry)
                await db_mutations_merchant.record_sale(npc_id, merchant.state, item_id, quantity, 0, conn=conn)
                await db_mutations_inventory.transact_inventory(player_id, item_id, -quantity, conn=conn)
                merchant.inventory_owners.add(player_id)
                return receipt(
                    visit,
                    {
                        "status": "consigned",
                        "npc_id": npc_id,
                        **entry,
                        "days_until_sale": entry["sale_day"] - merchant.today,
                        "expiry_day": expires_on(entry),
                    },
                )

        await db_mutations_merchant.record_sale(npc_id, merchant.state, item_id, quantity, total_sp, conn=conn)
        await db_mutations_inventory.transact_inventory(player_id, item_id, -quantity, conn=conn)
        merchant.inventory_owners.add(player_id)
        await visit.credit(total_sp / visit.pricing["silver_per_gold"], "sale")
        response = receipt(
            visit,
            {
                "status": "sold",
                "item_id": item_id,
                "npc_id": npc_id,
                "quantity": quantity,
                "unit_price_sp": total_sp // quantity if total_sp % quantity == 0 else None,
                "total_price_sp": total_sp,
            },
        )

    await publish_action_sound(context.userdata, ACTION_SOUND_EXPORTS["ACTION_SELL_ITEM"])
    return response
