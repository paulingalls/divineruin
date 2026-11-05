"""Recipe eligibility and concrete stack deductions under inventory locks."""

import json

import db_mutations


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


def purification_output(source_item_id):
    if source_item_id == "corruption_saturated_stone":
        raise ValueError("corruption_saturated_stone is unpurifiable")
    return "battleaxe_common" if source_item_id == "salvageable_weapon" else source_item_id


async def credit_clean(connection, owner_id, source_item_id, quantity):
    """Credit purified units on the caller's transaction; escrow callers must not debit held stacks."""
    output_id = purification_output(source_item_id)
    if quantity <= 0:
        raise ValueError("Purification requires a positive quantity")
    await db_mutations.add_inventory_item(owner_id, output_id, quantity, tainted=False, conn=connection)
    return output_id


async def purify_held_stack(connection, owner_id, source_item_id):
    """Move one whole held tainted stack using the caller's transaction and owner locks."""
    purification_output(source_item_id)
    row = await connection.fetchrow(
        "SELECT COALESCE((data->>'quantity')::int, 1) AS quantity FROM player_inventory "
        "WHERE player_id=$1 AND item_id=$2 AND tainted=true FOR UPDATE",
        owner_id,
        source_item_id,
    )
    if row is None or row["quantity"] <= 0:
        raise ValueError(f"No tainted stack of {source_item_id} is held by {owner_id}")
    quantity = row["quantity"]
    await connection.execute(
        "DELETE FROM player_inventory WHERE player_id=$1 AND item_id=$2 AND tainted=true",
        owner_id,
        source_item_id,
    )
    output_id = await credit_clean(connection, owner_id, source_item_id, quantity)
    return dict(player_id=owner_id, source_item_id=source_item_id, item_id=output_id, quantity=quantity)
