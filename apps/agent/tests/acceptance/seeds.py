"""Seeding helpers for Postgres-backed acceptance tests.

Content tables (locations, training_programs, ...) are seeded wholesale by
scripts/seed_content.py::seed; these helpers add the per-test player and
training rows that the scenarios drive against.
"""

from __future__ import annotations

import json

import asyncpg

_DEFAULT_PLAYER = {
    "name": "Acceptance Tester",
    "level": 2,
    "attributes": {
        "strength": 12,
        "dexterity": 16,
        "constitution": 14,
        "intelligence": 10,
        "wisdom": 13,
        "charisma": 8,
    },
    "proficiencies": ["stealth", "perception"],
    "saving_throw_proficiencies": ["strength", "dexterity"],
    "hp": {"current": 28, "max": 28},
    "ac": 15,
}


async def seed_player(
    conn: asyncpg.Connection | asyncpg.Pool,
    *,
    player_id: str = "player_1",
    class_: str = "skirmisher",
    location_id: str = "accord_guild_hall",
) -> str:
    """Upsert a player row with a valid archetype and starting location."""
    data = {**_DEFAULT_PLAYER, "player_id": player_id, "class": class_, "location_id": location_id}
    await conn.execute(
        """
        INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb)
        ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb
        """,
        player_id,
        json.dumps(data),
    )
    return player_id


async def clear_training_activities(conn: asyncpg.Connection | asyncpg.Pool, player_id: str = "player_1") -> None:
    """Drop any training rows so each scenario starts from an empty slot."""
    await conn.execute("DELETE FROM training_activities WHERE player_id = $1", player_id)


async def seed_training_activity(
    conn: asyncpg.Connection | asyncpg.Pool,
    *,
    activity_id: str,
    player_id: str = "player_1",
    activity_type: str = "technique_base",
    state: str = "running_first_half",
    data: dict | None = None,
) -> str:
    """Insert a training_activities row in a given state (for resolve / slot-conflict
    scenarios that need a pre-existing cycle)."""
    payload = data if data is not None else {"program_id": "combat_basics", "program_name": "Combat Fundamentals"}
    await conn.execute(
        """
        INSERT INTO training_activities (id, player_id, activity_type, state, data)
        VALUES ($1, $2, $3, $4, $5::jsonb)
        ON CONFLICT (id) DO UPDATE SET state = $4, data = $5::jsonb
        """,
        activity_id,
        player_id,
        activity_type,
        state,
        json.dumps(payload),
    )
    return activity_id
