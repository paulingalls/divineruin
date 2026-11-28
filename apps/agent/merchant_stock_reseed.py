"""Reseed-time repair of merchant shelves the new content no longer stocks."""

import asyncpg


async def drop_stale_merchant_stock(conn: asyncpg.Connection) -> None:
    """Unstock merchants whose shelf holds an item their bound pool no longer stocks.

    A content reseed can remove a pool item or rebind a merchant. `lock_merchant` refuses an
    untracked item as corruption, so the reseed drops `current_inventory` instead; the next
    visit restocks the row once and keeps the day's purse and buyback history.
    """
    await conn.execute(
        """
        UPDATE merchant_state m SET data = m.data - 'current_inventory'
        FROM npcs n JOIN inventory_pools p ON p.id = n.data->>'inventory_pool'
        WHERE n.id = m.npc_id AND EXISTS (
            SELECT 1 FROM jsonb_object_keys(m.data->'current_inventory') AS held(item_id)
            WHERE held.item_id NOT IN (
              SELECT e->>'item_id' FROM jsonb_array_elements((p.data->'tier_2_items') || (p.data->'tier_3_items')) e
            )
          )
        """
    )
