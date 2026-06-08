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
    companion: dict | None = None,
) -> str:
    """Upsert a player row with a valid archetype and starting location.

    Pass `companion` to attach a companion block (the errand resolve path reads
    `player_data["companion"]`, and the DM needs the companion id to dispatch).
    """
    data = {**_DEFAULT_PLAYER, "player_id": player_id, "class": class_, "location_id": location_id}
    if companion is not None:
        data["companion"] = companion
    await conn.execute(
        """
        INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb)
        ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb
        """,
        player_id,
        json.dumps(data),
    )
    return player_id


async def seed_player_with_pools(
    conn: asyncpg.Connection | asyncpg.Pool,
    *,
    player_id: str = "player_1",
    class_: str = "skirmisher",
    stamina_current: int = 10,
    focus_current: int = 10,
) -> str:
    """seed_player + add the Stamina/Focus pools the ability-activation tool reads.

    seed_player's default has no pools; jsonb_set on the top-level '{stamina}' /
    '{focus}' keys (parent `data` exists) initializes them. Shared by the M2.2 and
    M9 ability/variant capstones, which deduct real Stamina/Focus on activation.
    """
    await seed_player(conn, player_id=player_id, class_=class_)
    await conn.execute(
        "UPDATE players SET data = jsonb_set(jsonb_set(data, '{stamina}', $2::jsonb), '{focus}', $3::jsonb) "
        "WHERE player_id = $1",
        player_id,
        json.dumps({"current": stamina_current, "max": 10}),
        json.dumps({"current": focus_current, "max": 10}),
    )
    return player_id


async def clear_training_activities(conn: asyncpg.Connection | asyncpg.Pool, player_id: str = "player_1") -> None:
    """Drop any training rows so each scenario starts from an empty slot."""
    await conn.execute("DELETE FROM training_activities WHERE player_id = $1", player_id)


async def clear_async_activities(conn: asyncpg.Connection | asyncpg.Pool, player_id: str = "player_1") -> None:
    """Drop any async_activities (crafting/companion_errand) so the companion slot starts empty."""
    await conn.execute("DELETE FROM async_activities WHERE player_id = $1", player_id)


async def seed_async_activity(
    conn: asyncpg.Connection | asyncpg.Pool,
    *,
    activity_id: str,
    player_id: str = "player_1",
    errand_type: str = "scout",
    destination: str = "millhaven",
    status: str = "in_progress",
    resolve_at: str | None = None,
) -> str:
    """Insert a companion_errand async_activities row, mirroring the dispatch tool's
    data shape (errand_tools._dispatch_companion_errand_impl) field-for-field so the
    async worker treats it identically to a tool-dispatched errand."""
    data = {
        "status": status,
        "activity_type": "companion_errand",
        "start_time": "2026-01-01T00:00:00+00:00",
        "duration_min_seconds": 14400,
        "duration_max_seconds": 28800,
        "resolve_at": resolve_at or "2026-01-01T01:00:00+00:00",
        "parameters": {"errand_type": errand_type, "destination": destination},
        "outcome": None,
        "narration_text": None,
        "narration_audio_url": None,
        "decision_options": None,
    }
    await conn.execute(
        """
        INSERT INTO async_activities (id, player_id, data) VALUES ($1, $2, $3::jsonb)
        ON CONFLICT (id) DO UPDATE SET data = $3::jsonb
        """,
        activity_id,
        player_id,
        json.dumps(data),
    )
    return activity_id


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
