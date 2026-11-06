"""Pending Echo choices share the caster's existing transaction and row lock."""

import json


async def store(player_id: str, pending: dict, *, conn) -> None:
    await conn.execute(
        "UPDATE players SET data = jsonb_set(data, '{pending_hollow_echo_choice}', $2::jsonb) WHERE player_id = $1",
        player_id,
        json.dumps(pending),
    )


async def consume(player_id: str, *, conn) -> None:
    await conn.execute("UPDATE players SET data = data - 'pending_hollow_echo_choice' WHERE player_id = $1", player_id)
