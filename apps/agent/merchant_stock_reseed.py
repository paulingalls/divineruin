"""Reseed-time repair of merchant shelves the new content no longer stocks."""

import asyncpg


async def drop_stale_merchant_stock(conn: asyncpg.Connection) -> None:
    """Preserve today's sales across reseeds. A shelf with no surviving keys restocks on its next visit."""
    await conn.execute(
        """
        UPDATE merchant_state m
        SET data = jsonb_set_lax(
            m.data,
            '{current_inventory}',
            (
                SELECT jsonb_object_agg(held.item_id, held.quantity)
                FROM jsonb_each(m.data->'current_inventory') AS held(item_id, quantity)
                WHERE held.item_id = ANY(pool_stock.item_ids)
            ),
            true,
            'delete_key'
        )
        FROM npcs n JOIN inventory_pools p ON p.id = n.data->>'inventory_pool'
        CROSS JOIN LATERAL (
            SELECT ARRAY(
                SELECT entry->>'item_id'
                FROM jsonb_array_elements((p.data->'tier_2_items') || (p.data->'tier_3_items')) entry
            ) AS item_ids
        ) pool_stock
        WHERE n.id = m.npc_id
          AND NOT (ARRAY(SELECT jsonb_object_keys(m.data->'current_inventory')) <@ pool_stock.item_ids)
        """
    )
