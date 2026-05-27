"""Inventory item-instance-state write operations.

Sibling to db_mutations.py, which holds inventory quantity/equip writes
(add_inventory_item, remove_inventory_item, consume_player_materials). This module
owns per-instance state on an inventory row — currently durability current_hits —
and exists as its own SRP module to keep db_mutations.py under the 500-line cap
(same call as the db_mutations_divine.py touch-split). All async, accept optional
conn where they participate in a caller transaction.
"""

import json

import asyncpg

import db


async def update_item_durability(
    player_id: str,
    item_id: str,
    current_hits: int,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Set current_hits on a single player_inventory row (per-instance durability).

    current_hits is per-instance player state on the inventory row's JSONB; the
    catalog durability_tier is untouched. Combat hit emission (story-003) writes the
    post-damage value computed by durability.apply_durability_damage.
    """
    _conn = conn or await db.get_pool()
    await _conn.execute(
        """
        UPDATE player_inventory
        SET data = jsonb_set(data, '{current_hits}', $3::jsonb)
        WHERE player_id = $1 AND item_id = $2
        """,
        player_id,
        item_id,
        json.dumps(current_hits),
    )
