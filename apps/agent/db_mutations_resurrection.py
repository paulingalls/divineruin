"""DB persistence for M4.4 resurrection (story-003).

Its own module (db_mutations.py is over the 500-line cap), same shape as db_mutations_death /
db_mutations_conditions. Writes the cost + revive state on players.data JSONB:
- attributes.<attr>  — permanent attribute penalty (delta, accumulates)
- maxhp_override      — negative int, the death-7+ -1/level fraying (delta, accumulates)
- hp.current + location_id — the revive (HP + anchor placement)
- last_rested_settlement_id — anchor tier-3 state (forward-seam; no rest caller writes it yet)

All accept conn= for transaction participation, mirroring the sibling mutation modules.
"""

import json

import asyncpg

import db
from catalog_parse import ATTRIBUTE_KEYS

# Gate the dynamic jsonb path so a bad key can't be written. Canonical six (catalog_parse SSOT).
_VALID_ATTRS = frozenset(ATTRIBUTE_KEYS)


async def apply_attribute_penalty(
    player_id: str,
    attribute: str,
    delta: int,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Add ``delta`` (negative for a penalty) to players.data.attributes.<attribute>, in SQL so the
    read-modify-write is one atomic statement. Fails loud on an unrecognized attribute."""
    if attribute not in _VALID_ATTRS:
        raise ValueError(f"unknown attribute: {attribute!r}")
    _conn = conn or await db.get_pool()
    await _conn.execute(
        "UPDATE players SET data = jsonb_set(data, ARRAY['attributes', $2], "
        "to_jsonb(COALESCE((data #>> ARRAY['attributes', $2])::int, 10) + $3)) "
        "WHERE player_id = $1",
        player_id,
        attribute,
        delta,
    )


async def apply_maxhp_override_delta(
    player_id: str,
    delta: int,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Add ``delta`` to players.data.maxhp_override (negative; accumulates across death-7+ deaths)."""
    _conn = conn or await db.get_pool()
    await _conn.execute(
        "UPDATE players SET data = jsonb_set(data, '{maxhp_override}', "
        "to_jsonb(COALESCE((data->>'maxhp_override')::int, 0) + $2)) WHERE player_id = $1",
        player_id,
        delta,
    )


async def revive_player(
    player_id: str,
    location_id: str,
    hp_current: int,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Place the returning character: set data.location_id and data.hp.current. ``hp_current`` is the
    caller's already-clamped value (trigger_character_death clamps to the post-override effective max)."""
    _conn = conn or await db.get_pool()
    await _conn.execute(
        "UPDATE players SET data = jsonb_set("
        "jsonb_set(data, '{location_id}', $2::jsonb), '{hp,current}', $3::jsonb) "
        "WHERE player_id = $1",
        player_id,
        json.dumps(location_id),
        json.dumps(hp_current),
    )


async def set_last_rested_settlement(
    player_id: str,
    location_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Record the player's last-rested settlement (anchor tier-3). Called on a long rest in a
    settlement (rest_mechanics); the resolver reads it when no same-region settlement exists."""
    _conn = conn or await db.get_pool()
    await _conn.execute(
        "UPDATE players SET data = jsonb_set(data, '{last_rested_settlement_id}', $2::jsonb) WHERE player_id = $1",
        player_id,
        json.dumps(location_id),
    )


async def read_last_rested_settlement(
    player_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> str | None:
    """Return the player's last-rested settlement id, or None when unset/absent."""
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow(
        "SELECT data->>'last_rested_settlement_id' AS last_rested_settlement_id FROM players WHERE player_id = $1",
        player_id,
    )
    if row is None:
        return None
    return row["last_rested_settlement_id"]
