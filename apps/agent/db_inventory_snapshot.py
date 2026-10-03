"""Atomic owner revision and item/material inventory projection."""

import json

import db
from asset_utils import compute_item_image_url


def project_inventory(rows) -> list[dict]:
    results = []
    for row in rows:
        if row["item_id"] is None:
            continue
        if row["item_data"] is not None:
            item = json.loads(row["item_data"])
        elif row["material_data"] is not None:
            item = json.loads(row["material_data"])
            item["type"] = "material"
        else:
            raise ValueError(f"Inventory id {row['item_id']!r} has no item or material catalog entry")
        slot = json.loads(row["slot_data"])
        item["slot_info"] = slot
        image_url = compute_item_image_url(item)
        if image_url:
            item["image_url"] = image_url
        results.append(item)
    return results


async def get_inventory_snapshot(player_id: str, *, conn=None) -> dict:
    connection = conn or await db.get_pool()
    rows = await connection.fetch(
        """
        SELECT p.inventory_revision::text, pi.item_id, i.data AS item_data,
               m.data AS material_data, pi.data AS slot_data
        FROM players p
        LEFT JOIN player_inventory pi ON pi.player_id = p.player_id
        LEFT JOIN items i ON i.id = pi.item_id
        LEFT JOIN materials_catalog m ON m.id = pi.item_id
        WHERE p.player_id = $1
        ORDER BY pi.item_id
        """,
        player_id,
    )
    if not rows:
        raise ValueError(f"Unknown inventory owner {player_id!r}")
    return {
        "player_id": player_id,
        "inventory_revision": rows[0]["inventory_revision"],
        "inventory": project_inventory(rows),
    }
