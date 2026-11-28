import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal

import asyncpg
from livekit.agents import Agent
from livekit.agents.llm import ChatContext, ToolError, function_tool
from livekit.agents.voice import RunContext

import db
import db_content_queries
import db_mutations_inventory
import db_mutations_merchant
import db_queries
import event_types as E
import inventory_pools
import pricing_queries
from catalog_parse import parse_dict
from consignment import Consignment, expires_on, proceeds_sp
from db_errors import db_tool
from game_events import publish_game_event
from inventory_pools import InventoryPool
from inventory_refresh import inventory_payload
from sale_pricing import economy_size, economy_traits, merchant_gold_allocation
from session_data import SessionData
from tool_preconditions import require_npc_present
from tool_support import _validate_id


@dataclass
class MerchantVisit:
    conn: asyncpg.Connection
    npc: dict
    pool: InventoryPool
    pools: dict[str, InventoryPool]
    pricing: dict
    merchant: db_mutations_merchant.LockedMerchant
    player_id: str
    currency: dict | None = None

    async def credit(self, amount: Decimal | float, source: str) -> None:
        balance = await db_mutations_inventory.credit_player_gold(self.player_id, amount, conn=self.conn)
        self.currency = {
            "player_id": self.player_id,
            "amount": float(amount),
            "currency": "gold",
            "source": source,
            "new_balance": balance,
        }


@asynccontextmanager
async def merchant_visit(context: RunContext[SessionData], npc_id: str) -> AsyncIterator[MerchantVisit]:
    _validate_id(npc_id, "npc_id")
    context.disallow_interruptions()
    session = context.userdata
    player_id = session.acting_player_id
    location_id = session.location_id
    await require_npc_present(location_id, npc_id, suffix=" to trade")
    async with db.transaction() as conn:
        npc = await db_content_queries.get_npc(npc_id, conn=conn)
        if npc is None:
            raise ToolError(f"Unknown merchant: {npc_id}")
        pool_id = npc["inventory_pool"]
        if pool_id is None:
            raise ToolError(f"{npc['name']} doesn't buy goods.")
        pools = await inventory_pools.get_inventory_pools(conn=conn)
        pool = pools[pool_id]
        pricing = await pricing_queries.get_economy_pricing(conn=conn)
        location = await db_content_queries.get_location(location_id, conn=conn)
        allocation = merchant_gold_allocation(pool, location, pricing, location_id=location_id)
        location_ctx = f"locations[{location_id}]"
        location_data = parse_dict(location, location_ctx)
        merchant = await db_mutations_merchant.lock_merchant(
            npc_id,
            allocation,
            player_id,
            pool=pool,
            size=economy_size(location_data.get("settlement_tier"), location_ctx),
            traits=economy_traits(location_data.get("personality"), location_ctx),
            pricing=pricing,
            conn=conn,
        )
        visit = MerchantVisit(conn, npc, pool, pools, pricing, merchant, player_id)
        yield visit
        session.validate_acting_player(player_id)

    if visit.currency is not None:
        await publish_game_event(session.room, E.CURRENCY_GAINED, visit.currency, event_bus=session.event_bus)
    for owner in sorted(merchant.inventory_owners):
        await publish_game_event(
            session.room,
            E.INVENTORY_UPDATED,
            await inventory_payload(owner),
            event_bus=session.event_bus,
            destination_identities=[owner] if owner != player_id else None,
        )


def receipt(visit: "MerchantVisit", payload: dict) -> str:
    """Serialize a merchant receipt with any unreported returns for the actor."""
    returned = [
        {"consignment_id": entry["consignment_id"], "item_id": entry["item_id"], "quantity": entry["quantity"]}
        for entry in visit.merchant.returned
    ]
    if returned:
        payload["returned"] = returned
    return json.dumps(payload)


def _ledger_entry(entry: Consignment, today: int) -> dict:
    return {
        "consignment_id": entry["consignment_id"],
        "item_id": entry["item_id"],
        "quantity": entry["quantity"],
        "sale_day": entry["sale_day"],
        "expiry_day": expires_on(entry),
        "full_price_sp": entry["full_price_sp"],
        "amount_sp": float(proceeds_sp(entry)),
        "status": "ready" if today >= entry["sale_day"] else "pending",
    }


@function_tool()
@db_tool
async def query_merchant_ledger(context: RunContext[SessionData], npc_id: str) -> str:
    """Read the acting player's pending consignments and coin waiting at a present merchant.

    Args:
        npc_id: The merchant ID from the present NPCs shared at trade entry.
    """
    async with merchant_visit(context, npc_id) as visit:
        entries = [
            _ledger_entry(entry, visit.merchant.today)
            for entry in visit.merchant.state["consigned_items"]
            if entry["consignor_id"] == visit.player_id
        ]
        return receipt(visit, {"npc_id": npc_id, "entries": entries})


@function_tool()
@db_tool
async def collect_consignment(context: RunContext[SessionData], npc_id: str, consignment_id: str) -> str:
    """Collect the acting player's coin for one ready consignment from a present merchant.

    Args:
        npc_id: The merchant ID from the present NPCs shared at trade entry.
        consignment_id: The consignment ID returned by query_merchant_ledger.
    """
    _validate_id(consignment_id, "consignment_id")
    async with merchant_visit(context, npc_id) as visit:
        merchant = visit.merchant
        entries = merchant.state["consigned_items"]
        entry = next(
            (entry for entry in [*entries, *merchant.returned] if entry["consignment_id"] == consignment_id), None
        )
        if entry is None or entry["consignor_id"] != visit.player_id:
            raise ToolError("You have no consignment with that ID here.")
        result = {"consignment_id": consignment_id, "item_id": entry["item_id"], "quantity": entry["quantity"]}
        if entry in merchant.returned:
            return receipt(visit, {"status": "returned", **result})
        if merchant.today < entry["sale_day"]:
            raise ToolError("That consignment has not sold yet.")
        amount_sp = proceeds_sp(entry)
        entries.remove(entry)
        await db_mutations_merchant.write_merchant(npc_id, merchant.state, conn=visit.conn)
        await visit.credit(amount_sp / Decimal(visit.pricing["silver_per_gold"]), "consignment")
        return receipt(visit, {"status": "collected", "amount_sp": float(amount_sp), **result})


async def _enter_trade_impl(context: RunContext[SessionData]) -> tuple[Agent, str]:
    from merchant_agent import MerchantAgent

    session = context.userdata
    caller = context.session.current_agent
    region = getattr(caller, "_agent_type", None) or await db_content_queries.get_location_region_type(
        session.location_id
    )
    present = await db_queries.get_npcs_at_location(session.location_id)
    npcs = [{"id": npc["id"], "name": npc["name"], "voice_id": npc.get("voice_id")} for npc in present]
    chat = ChatContext()
    chat.add_message(
        role="system",
        content=f"Present NPCs at {session.location_id} (id, name and voice key):\n{json.dumps(npcs)}",
    )

    for message in reversed(caller.chat_ctx.messages()):
        if message.role == "user" and message.text_content:
            chat.add_message(role="user", content=message.text_content)
            break

    merchant = MerchantAgent(chat_ctx=chat)
    session.pre_trade_agent_type = region
    return merchant, json.dumps({"status": "entered_trade", "location_id": session.location_id, "present_npcs": npcs})


@function_tool()
@db_tool
async def conclude_trade(context: RunContext[SessionData]) -> tuple[Agent, str]:
    """Return to ordinary play when the player is finished selling or wants to leave."""
    from gameplay_agent import create_gameplay_agent

    session = context.userdata
    region = session.pre_trade_agent_type or await db_content_queries.get_location_region_type(session.location_id)
    chat = ChatContext()
    chat.add_message(role="system", content="The trade conversation is finished. Continue at the current location.")
    exploration = create_gameplay_agent(region, session.location_id, companion=session.companion, chat_ctx=chat)
    session.pre_trade_agent_type = None
    return exploration, json.dumps({"status": "concluded_trade"})
