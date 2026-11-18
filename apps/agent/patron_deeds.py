"""Patron deeds accumulated and consumed inside caller-owned transactions."""

import json

import asyncpg

from _gods_content import load_gods
from favor_rules import evaluate_patron_alignment
from progression_tools import FavorGrant, _award_divine_favor_core


async def record_deed(player_id: str, kind: str, *, conn: asyncpg.Connection) -> None:
    if not any(
        row["action"] == kind
        for god in load_gods()
        for category in ("positive", "negative")
        for row in god["favor_actions"][category]
    ):
        raise ValueError(f"Unknown deed kind '{kind}'")
    row = await conn.fetchrow(
        """UPDATE players SET data = jsonb_set(data, '{patron_deeds}',
            COALESCE(data->'patron_deeds', '{}'::jsonb) || jsonb_build_object($2::text,
                CASE WHEN data->'patron_deeds'->>$2 = 'awarded' THEN 'awarded' ELSE 'pending' END))
            WHERE player_id = $1 RETURNING player_id""",
        player_id,
        kind,
    )
    if row is None:
        raise ValueError(f"Player '{player_id}' not found")


async def mark_awarded(player_id: str, kind: str, *, conn: asyncpg.Connection) -> None:
    row = await conn.fetchrow(
        """UPDATE players SET data = jsonb_set(data, '{patron_deeds}',
            COALESCE(data->'patron_deeds', '{}'::jsonb) || jsonb_build_object($2::text, 'awarded'::text))
            WHERE player_id = $1 RETURNING player_id""",
        player_id,
        kind,
    )
    if row is None:
        raise ValueError(f"Player '{player_id}' not found")


async def judge_pending_deeds(
    player_id: str, *, conn: asyncpg.Connection, pending_events: list[tuple[str, dict]]
) -> FavorGrant | None:
    row = await conn.fetchrow("SELECT data FROM players WHERE player_id = $1 FOR UPDATE", player_id)
    if row is None:
        raise ValueError(f"Player '{player_id}' not found")
    data = json.loads(row["data"])
    deeds = data.get("patron_deeds", {})
    if not deeds:
        return None
    favor = data.get("divine_favor")
    grant = None
    if favor is not None and favor.get("patron", "none") != "none":
        patron = next((god for god in load_gods() if god["god_id"] == favor["patron"]), None)
        if patron is None:
            raise ValueError(f"Unknown patron '{favor['patron']}'")
        grant = await _award_divine_favor_core(
            player_id,
            evaluate_patron_alignment(deeds, patron),
            "Patron deed judgment",
            conn=conn,
            pending_events=pending_events,
        )
    await conn.execute(
        "UPDATE players SET data = jsonb_set(data, '{patron_deeds}', '{}'::jsonb) WHERE player_id = $1",
        player_id,
    )
    return grant
