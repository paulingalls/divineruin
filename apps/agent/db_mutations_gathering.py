"""DB persistence for gathering-node mutations (M4.6c, story-003).

Its own module (not db_mutations.py, already over the 500-line cap) keeps the gathering feature
cohesive — same shape as db_mutations_travel / db_mutations_conditions. Fixed nodes live in the
gathering_nodes table (id, data JSONB; migration 056). story-003's gather action marks a node
discovered and depletes its quantity; M16's world-sim tick will later restore quantity per
respawn_days. Both mutate via 1-level jsonb_set on data. Accepts conn= for transaction participation.
"""

import asyncpg

import db


async def mark_node_discovered(node_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None) -> None:
    """Set a gathering node's data.discovered to true (idempotent). Once found, a node stays on
    the player's map for return visits (spec §Discovery)."""
    _conn = conn or await db.get_pool()
    await _conn.execute(
        "UPDATE gathering_nodes SET data = jsonb_set(data, '{discovered}', 'true'::jsonb) WHERE id = $1",
        node_id,
    )


async def deplete_node_quantity(
    node_id: str, amount: int, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> None:
    """Decrement a gathering node's data.quantity by `amount`, floored at 0 (a node depletes when
    gathered; spec §Node depletion). The respawn back toward the seeded max is M16's tick."""
    _conn = conn or await db.get_pool()
    await _conn.execute(
        "UPDATE gathering_nodes SET data = jsonb_set("
        "data, '{quantity}', to_jsonb(GREATEST(0, (data->>'quantity')::int - $2))) WHERE id = $1",
        node_id,
        amount,
    )


async def restore_node_quantity(
    node_id: str, quantity: int, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> None:
    """Set a gathering node's data.quantity to `quantity`, capped at data.capacity (M16's
    gathering_respawn.compute_node_respawn decides the target; this persists it). COALESCEs to
    the current quantity when a row predates the capacity field, so a capacity-less row no-ops
    instead of null-writing quantity (LEAST(NULL, x) would corrupt it)."""
    _conn = conn or await db.get_pool()
    await _conn.execute(
        "UPDATE gathering_nodes SET data = jsonb_set("
        "data, '{quantity}', "
        "to_jsonb(LEAST(COALESCE((data->>'capacity')::int, (data->>'quantity')::int), $2))) "
        "WHERE id = $1",
        node_id,
        quantity,
    )
