"""Stack-scoped durability and signed quantity mutations."""

import json

import asyncpg

import db
import db_mutations


async def update_item_durability(
    player_id: str,
    item_id: str,
    current_hits: int,
    *,
    tainted: bool = False,
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
        WHERE player_id = $1 AND item_id = $2 AND tainted = $4
        """,
        player_id,
        item_id,
        json.dumps(current_hits),
        tainted,
    )


async def transact_inventory(
    player_id: str,
    item_id: str,
    delta: int,
    *,
    tainted: bool = False,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> int:
    """Decrement a stack's quantity by a negative delta; return the remaining quantity.

    The transact verb's LOSS path is the only caller — gains route through
    db_mutations.add_inventory_item (which inserts a missing row), so delta is
    always negative here. The signed UPDATE would increment on a positive delta,
    but that path is unused by design; pass gains to add_inventory_item instead.

    When the result is at or below zero the row is deleted (via
    db_mutations.remove_inventory_item) and 0 is returned. Single UPDATE ...
    RETURNING — no read-compute-write — so the decrement is atomic within the
    caller transaction; the existence + equipped guards are the caller's FOR UPDATE
    read. A missing row raises ValueError rather than no-op'ing (fail loud, a
    caller-invariant violation, matching the sibling consume_player_materials).

    Over-decrementing (|delta| greater than the stock on hand) deliberately floors
    the remaining count at 0 and deletes the row, mirroring the legacy whole-stack
    remove_from_inventory: losing more than you hold simply empties the stack.
    """
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow(
        f"""
        UPDATE player_inventory
        SET data = {db_mutations.quantity_delta_expr("data", "$3")}
        WHERE player_id = $1 AND item_id = $2 AND tainted = $4
        RETURNING (data->>'quantity')::int AS quantity
        """,
        player_id,
        item_id,
        delta,
        tainted,
    )
    if row is None:
        raise ValueError(f"No inventory row for player {player_id!r} item {item_id!r} to transact.")
    remaining = row["quantity"]
    if remaining <= 0:
        await db_mutations.remove_inventory_item(player_id, item_id, tainted=tainted, conn=_conn)
        return 0
    return remaining
