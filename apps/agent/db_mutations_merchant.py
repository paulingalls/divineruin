"""Lazy merchant state and settlement writes on the caller's transaction."""

import json
from datetime import UTC, datetime
from typing import cast

import asyncpg

from aethos_clock import aethos_day
from merchant_purse import MerchantState


def aethos_today() -> int:
    return aethos_day(datetime.now(UTC))


async def lock_merchant(npc_id: str, allocation: int, *, conn: asyncpg.Connection) -> MerchantState:
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
    if inserted:
        state["consigned_items"] = []
    if inserted or state["last_restock_day"] < today:
        state.update(current_gold_sp=allocation, max_gold_sp=allocation, last_restock_day=today, buyback_history={})
        await _write_merchant(npc_id, state, conn=conn)
    return state


async def debit_merchant(
    npc_id: str, state: MerchantState, item_id: str, quantity: int, total_sp: int, *, conn: asyncpg.Connection
) -> None:
    state["current_gold_sp"] -= total_sp
    history = state["buyback_history"]
    history[item_id] = history.get(item_id, 0) + quantity
    await _write_merchant(npc_id, state, conn=conn)


async def _write_merchant(npc_id: str, state: MerchantState, *, conn: asyncpg.Connection) -> None:
    await conn.execute("UPDATE merchant_state SET data = $2::jsonb WHERE npc_id = $1", npc_id, json.dumps(state))
