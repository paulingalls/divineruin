"""Transactional persistence for in-flight journeys and hours since a long rest."""

import json

import asyncpg

import db


async def update_player_travel_state(
    player_id: str, travel_state: dict | None, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> None:
    """Persist players.data.travel_state: null when not travelling, or a journey dict. Accepts
    None → JSON null (cleared on arrival). A 1-level jsonb_set, written whether or not the key exists."""
    _conn = conn or await db.get_pool()
    await _conn.execute(
        "UPDATE players SET data = jsonb_set(data, '{travel_state}', $2::jsonb) WHERE player_id = $1",
        player_id,
        json.dumps(travel_state),
    )


async def add_travel_hours(player_id: str, hours: int, *, conn: asyncpg.Connection) -> None:
    await conn.execute(
        "UPDATE players SET data = jsonb_set(data, '{travel_hours_since_rest}', "
        "to_jsonb(COALESCE((data->>'travel_hours_since_rest')::int, 0) + $2)) WHERE player_id = $1",
        player_id,
        hours,
    )


async def reset_travel_hours(player_id: str, *, conn: asyncpg.Connection) -> None:
    await conn.execute(
        "UPDATE players SET data = jsonb_set(data, '{travel_hours_since_rest}', '0'::jsonb) WHERE player_id = $1",
        player_id,
    )
