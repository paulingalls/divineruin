"""Collect a resolved craft through the same activity row lock as the app."""

import json

from livekit.agents.llm import ToolError
from livekit.agents.voice import RunContext

import db
import db_activity_queries
import db_content_queries
import db_mutations
import event_types as E
import pricing_queries
from db_mutations_inventory import credit_player_gold
from game_events import publish_game_event
from inventory_refresh import publish_inventory
from sale_pricing import quote_sale
from session_data import SessionData


async def resolve_crafted_decision(context: RunContext[SessionData], activity_id: str, decision: str) -> str:
    context.disallow_interruptions()
    session = context.userdata
    player_id = session.acting_player_id
    receipt: dict = {"id": activity_id, "status": "collected", "decision": decision}
    currency = None

    async with db.transaction() as conn:
        activity = await db_activity_queries.get_activity(activity_id, conn=conn, for_update=True)
        if activity is None or activity["player_id"] != player_id:
            raise ToolError("Activity not found.")
        if activity["activity_type"] != "crafting":
            raise ToolError("This is not a crafting activity.")
        if activity["status"] != "resolved":
            raise ToolError("Crafting activity is not resolved or has already been collected.")
        if not any(option["id"] == decision for option in activity["decision_options"] or []):
            raise ToolError("That decision was not offered for this craft.")

        item_id = ""
        proceeds = None
        if decision in ("keep", "sell"):
            item_id = activity["outcome"]["crafted_item_id"]
            item = await db_content_queries.get_item(item_id, conn=conn) if item_id else None
            if item is None:
                raise ValueError(f"Activity {activity_id} has no crafted item for {decision}: {item_id!r}")
            if decision == "sell":
                pricing = await pricing_queries.get_economy_pricing(conn=conn)
                quote = quote_sale(item, pricing, kind="crafted")
                if not quote["available"]:
                    raise ToolError(f"This craft cannot be sold: {quote['reason']}.")
                proceeds = {"price_sp": quote["price_sp"], "gold": quote["price_sp"] / pricing["silver_per_gold"]}

        session.validate_acting_player(player_id)
        if decision == "keep":
            await db_mutations.add_inventory_item(player_id, item_id, quantity=1, tainted=False, conn=conn)
            receipt["item_id"] = item_id
        elif proceeds is not None:
            balance = await credit_player_gold(player_id, proceeds["gold"], conn=conn)
            receipt["proceeds"] = proceeds
            currency = {
                "player_id": player_id,
                "amount": proceeds["gold"],
                "currency": "gold",
                "source": "crafting",
                "new_balance": balance,
            }
        await db_mutations.update_activity(activity_id, {"status": "collected", "decision": decision}, conn=conn)

    if decision == "keep":
        await publish_inventory(session, player_id)
    elif currency is not None:
        await publish_game_event(session.room, E.CURRENCY_GAINED, currency, event_bus=session.event_bus)
    return json.dumps(receipt)
