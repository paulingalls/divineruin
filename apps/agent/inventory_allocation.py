"""Recipe eligibility and concrete stack deductions under inventory locks."""

import json


async def read_stacks(connection, player_id, *, for_update=False):
    query = """SELECT item_id, tainted, COALESCE((data->>'quantity')::int, 1) AS quantity
        FROM player_inventory WHERE player_id = $1 ORDER BY item_id, tainted"""
    if for_update:
        query += " FOR UPDATE"
    return await connection.fetch(query, player_id)


def eligible_stacks(rows, *, allow_tainted=False):
    return [row for row in rows if allow_tainted or not row["tainted"]]


def eligible_totals(rows, *, allow_tainted=False):
    totals = {}
    for row in eligible_stacks(rows, allow_tainted=allow_tainted):
        totals[row["item_id"]] = totals.get(row["item_id"], 0) + row["quantity"]
    return totals


def allocate_stacks(rows, allocation, *, allow_tainted=False):
    available = eligible_totals(rows, allow_tainted=allow_tainted)
    for item_id, quantity in allocation.items():
        if quantity < 0 or available.get(item_id, 0) < quantity:
            raise ValueError(f"consume_player_materials: allocation exceeds held quantity for {item_id}")
    usable = eligible_stacks(rows, allow_tainted=allow_tainted)
    deductions = []
    for item_id, quantity in sorted(allocation.items()):
        for row in sorted((r for r in usable if r["item_id"] == item_id), key=lambda r: not r["tainted"]):
            take = min(quantity, row["quantity"])
            if take:
                deductions.append((item_id, row["tainted"], row["quantity"] - take))
                quantity -= take
    return deductions


async def consume(connection, player_id, allocation, *, allow_tainted=False):
    rows = await read_stacks(connection, player_id, for_update=True)
    deductions = allocate_stacks(rows, allocation, allow_tainted=allow_tainted)
    for item_id, tainted, remaining in deductions:
        if remaining:
            await connection.execute(
                "UPDATE player_inventory SET data = jsonb_set(data, '{quantity}', $3::jsonb) "
                "WHERE player_id = $1 AND item_id = $2 AND tainted = $4",
                player_id,
                item_id,
                json.dumps(remaining),
                tainted,
            )
        else:
            await connection.execute(
                "DELETE FROM player_inventory WHERE player_id = $1 AND item_id = $2 AND tainted = $3",
                player_id,
                item_id,
                tainted,
            )
