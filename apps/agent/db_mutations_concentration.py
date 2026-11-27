"""Read and write each player's concentration in its players.data record."""

import json
from dataclasses import asdict

import asyncpg

import db
from caster_state import ConcentrationState


async def read_player_concentration(
    player_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> dict:
    connection = conn or await db.get_pool()
    raw = await connection.fetchval("SELECT data->'concentration' FROM players WHERE player_id = $1", player_id)
    if raw is None:
        return {"spell_id": None}
    return json.loads(raw) if isinstance(raw, str) else raw


async def update_player_concentration(
    player_id: str,
    state: ConcentrationState | str | None,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    concentration = state if isinstance(state, ConcentrationState) else ConcentrationState(state)
    record = asdict(concentration) if concentration.is_active else {"spell_id": None}
    connection = conn or await db.get_pool()
    await connection.execute(
        "UPDATE players SET data = jsonb_set(data, '{concentration}', $2::jsonb) WHERE player_id = $1",
        player_id,
        json.dumps(record),
    )
