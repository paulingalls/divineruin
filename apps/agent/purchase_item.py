import hashlib
import json
from decimal import Decimal, localcontext
from typing import Annotated, cast

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext
from pydantic import Field

import db_content_queries
import db_mutations
import db_mutations_merchant
import db_mutations_sink
import db_queries
from action_sound_content import ACTION_SOUND_EXPORTS, publish_action_sound
from db_errors import db_tool
from disposition import resolve_disposition
from merchant_tools import merchant_visit, receipt
from purchase_pricing import PurchaseQuote, attempt_purchase
from session_data import SessionData
from tool_support import _validate_id


@function_tool()
@db_tool
async def purchase_item(
    context: RunContext[SessionData],
    item_id: str,
    npc_id: str,
    quantity: Annotated[int, Field(strict=True)],
    offer_id: str = "",
) -> str:
    """Get a price for goods from a present merchant, or buy them after the player consents.

    Args:
        item_id: The item ID from query_merchant_inventory.
        npc_id: The merchant ID from the present NPCs shared at trade entry.
        quantity: How many units the player wants to buy. Must be at least one.
        offer_id: Empty to quote. After reading the price aloud and getting consent, use the returned ID.
    """
    _validate_id(item_id, "item_id")
    if quantity < 1:
        raise ToolError("Buy at least one item.")

    async with merchant_visit(context, npc_id, no_pool_verb="trade") as visit:
        conn, player_id, merchant = visit.conn, visit.player_id, visit.merchant
        item = await db_content_queries.get_item(item_id, conn=conn)
        if item is None:
            raise ToolError(f"Unknown item: {item_id}")
        disposition = await resolve_disposition(
            npc_id, player_id, conn=conn, default_disposition=visit.npc.get("default_disposition", "neutral")
        )
        gold = cast(
            Decimal,
            await conn.fetchval(
                "SELECT COALESCE((data->>'gold')::numeric, 0) FROM players WHERE player_id=$1", player_id
            ),
        )
        silver_per_gold = Decimal(str(visit.pricing["silver_per_gold"]))
        with localcontext() as decimal_context:
            decimal_context.prec = len(gold.as_tuple().digits) + len(silver_per_gold.as_tuple().digits)
            balance_sp = gold * silver_per_gold
        quote = attempt_purchase(
            merchant.state,
            visit.pool,
            item,
            quantity,
            disposition,
            visit.traits,
            balance_sp=balance_sp,
            pricing=visit.pricing,
        )
        request = {"item_id": item_id, "npc_id": npc_id, "quantity": quantity}
        if not isinstance(quote, PurchaseQuote):
            return receipt(visit, {"status": "refused", **request, "reason": quote})

        total_sp = quote.total_price_sp
        terms = (
            player_id,
            npc_id,
            item_id,
            quantity,
            gold.as_integer_ratio(),
            total_sp,
            merchant.today,
            quote.stock_count,
        )
        current_offer = hashlib.sha256(json.dumps(terms).encode()).hexdigest()
        if offer_id != current_offer:
            return receipt(visit, {"status": "offer", **request, "total_price_sp": total_sp, "offer_id": current_offer})

        await db_mutations_merchant.record_purchase(npc_id, merchant.state, item_id, quantity, quote, conn=conn)
        balance = await visit.debit(Decimal(total_sp) / silver_per_gold, "merchant_purchase")
        await db_mutations.add_inventory_item(player_id, item_id, quantity, tainted=False, conn=conn)
        await db_mutations_sink.record_merchant_purchase(
            player_id,
            visit.pool["sink_category"],
            item_id,
            total_sp,
            {"npc_id": npc_id, "location_id": context.userdata.location_id, "quantity": quantity},
            conn=conn,
        )
        stack = await db_queries.get_inventory_item(player_id, item_id, conn=conn)
        assert stack is not None
        merchant.inventory_owners.add(player_id)
        response = receipt(
            visit,
            {
                "status": "purchased",
                **request,
                "total_price_sp": total_sp,
                "new_balance": balance,
                "new_item_count": stack["quantity"],
            },
        )

    await publish_action_sound(context.userdata, ACTION_SOUND_EXPORTS["ACTION_PURCHASE_ITEM"])
    return response
