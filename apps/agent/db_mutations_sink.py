import json

import asyncpg


async def record_merchant_purchase(
    player_id: str,
    sink_category: str,
    item_id: str,
    amount_sp: int,
    context: dict,
    *,
    conn: asyncpg.Connection,
) -> None:
    await conn.execute(
        """
        INSERT INTO sink_event_log (player_id, sink_category, sink_type, item_id, amount_sp, context)
        VALUES ($1, $2, 'merchant_purchase', $3, $4, $5::jsonb)
        """,
        player_id,
        sink_category,
        item_id,
        amount_sp,
        json.dumps(context),
    )
