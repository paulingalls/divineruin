"""Lazy merchant state and settlement writes on the caller's transaction."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

import asyncpg
from livekit.agents.llm import ToolError

import db_mutations
from aethos_clock import aethos_day
from consignment import Consignment, expires_on, read_ledger
from merchant_purse import MerchantState


@dataclass
class LockedMerchant:
    state: MerchantState
    today: int
    revision: int
    returned: list[Consignment]
    inventory_owners: set[str]


def aethos_today() -> int:
    return aethos_day(datetime.now(UTC))


async def lock_merchant(npc_id: str, allocation: int, player_id: str, *, conn: asyncpg.Connection) -> LockedMerchant:
    inserted = await conn.fetchval(
        """
        INSERT INTO merchant_state (npc_id, data) VALUES ($1, '{}'::jsonb)
        ON CONFLICT (npc_id) DO NOTHING RETURNING npc_id
        """,
        npc_id,
    )
    raw = await conn.fetchval("SELECT data FROM merchant_state WHERE npc_id = $1 FOR UPDATE", npc_id)
    if raw is None:
        raise RuntimeError(f"Missing merchant state after initialization: {npc_id}")

    today = aethos_today()
    state = cast(MerchantState, json.loads(raw))
    entries = [] if inserted else read_ledger(state["consigned_items"])
    remaining: list[Consignment] = []
    expired: list[Consignment] = []
    for entry in entries:
        (expired if today >= expires_on(entry) else remaining).append(entry)
    owners = {entry["consignor_id"] for entry in expired}
    locked = await conn.fetch(
        "SELECT player_id FROM players WHERE player_id = ANY($1) ORDER BY player_id FOR UPDATE",
        sorted(owners | {player_id}),
    )
    locked_ids = {row["player_id"] for row in locked}
    if player_id not in locked_ids:
        raise ToolError(f"Unknown player: {player_id}")
    if missing := owners - locked_ids:
        raise ValueError(f"Consignors missing from players: {sorted(missing)}")

    restock = inserted or state["last_restock_day"] < today
    if restock:
        state.update(current_gold_sp=allocation, max_gold_sp=allocation, last_restock_day=today, buyback_history={})
    for entry in expired:
        await db_mutations.add_inventory_item(
            entry["consignor_id"], entry["item_id"], entry["quantity"], tainted=False, conn=conn
        )
    # Only the owner's successful visit consumes the notice. Inventory is restored at expiry.
    unreported = read_ledger(state.pop("unreported_returns", []))
    returned = []
    other_returns = []
    for entry in [*unreported, *expired]:
        (returned if entry["consignor_id"] == player_id else other_returns).append(entry)
    if other_returns:
        state["unreported_returns"] = other_returns
    state["consigned_items"] = remaining
    if restock or expired or returned:
        await write_merchant(npc_id, state, conn=conn)

    revision = await conn.fetchval("SELECT inventory_revision FROM players WHERE player_id = $1", player_id)
    return LockedMerchant(state, today, cast(int, revision), returned, owners)


async def record_sale(
    npc_id: str, state: MerchantState, item_id: str, quantity: int, total_sp: int, *, conn: asyncpg.Connection
) -> None:
    state["current_gold_sp"] -= total_sp
    history = state["buyback_history"]
    history[item_id] = history.get(item_id, 0) + quantity
    await write_merchant(npc_id, state, conn=conn)


async def write_merchant(npc_id: str, state: MerchantState, *, conn: asyncpg.Connection) -> None:
    await conn.execute("UPDATE merchant_state SET data = $2::jsonb WHERE npc_id = $1", npc_id, json.dumps(state))
