"""Database write/mutation operations. All async, accept optional conn parameter."""

import json
import logging
import uuid

import asyncpg

import db

logger = logging.getLogger("divineruin.db")


async def update_player_hp(
    player_id: str, current_hp: int, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> None:
    _conn = conn or await db.get_pool()
    await _conn.execute(
        """
        UPDATE players
        SET data = jsonb_set(data, '{hp,current}', $2::jsonb)
        WHERE player_id = $1
        """,
        player_id,
        json.dumps(current_hp),
    )


async def update_npc_hp(npc_id: str, current_hp: int, *, conn: asyncpg.Connection | asyncpg.Pool | None = None) -> None:
    _conn = conn or await db.get_pool()
    await _conn.execute(
        """
        UPDATE npc_state
        SET data = jsonb_set(data, '{hp,current}', $2::jsonb)
        WHERE npc_id = $1
        """,
        npc_id,
        json.dumps(current_hp),
    )


async def update_player_location(
    player_id: str, location_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> None:
    _conn = conn or await db.get_pool()
    await _conn.execute(
        """
        UPDATE players
        SET data = jsonb_set(data, '{location_id}', $2::jsonb)
        WHERE player_id = $1
        """,
        player_id,
        json.dumps(location_id),
    )


async def update_player_xp(
    player_id: str, new_xp: int, new_level: int, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> None:
    _conn = conn or await db.get_pool()
    await _conn.execute(
        """
        UPDATE players
        SET data = jsonb_set(jsonb_set(data, '{xp}', $2::jsonb), '{level}', $3::jsonb)
        WHERE player_id = $1
        """,
        player_id,
        json.dumps(new_xp),
        json.dumps(new_level),
    )


async def update_skill_advancement(
    player_id: str,
    skill: str,
    tier: str,
    use_counter: int,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Upsert skill advancement record."""
    _conn = conn or await db.get_pool()
    await _conn.execute(
        """
        INSERT INTO skill_advancement (player_id, skill_id, tier, use_counter, updated_at)
        VALUES ($1, $2, $3, $4, NOW())
        ON CONFLICT (player_id, skill_id)
        DO UPDATE SET tier = $3, use_counter = $4, updated_at = NOW()
        """,
        player_id,
        skill,
        tier,
        use_counter,
    )


async def mark_narrative_moment(
    player_id: str, skill: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> None:
    """Set narrative_moment_ready flag for Expert→Master advancement."""
    _conn = conn or await db.get_pool()
    await _conn.execute(
        """
        INSERT INTO skill_advancement (player_id, skill_id, narrative_moment_ready, updated_at)
        VALUES ($1, $2, TRUE, NOW())
        ON CONFLICT (player_id, skill_id)
        DO UPDATE SET narrative_moment_ready = TRUE, updated_at = NOW()
        """,
        player_id,
        skill,
    )


async def clear_narrative_moment(
    player_id: str, skill: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> None:
    """Clear narrative_moment_ready flag after Expert→Master advancement."""
    _conn = conn or await db.get_pool()
    await _conn.execute(
        """
        UPDATE skill_advancement SET narrative_moment_ready = FALSE, updated_at = NOW()
        WHERE player_id = $1 AND skill_id = $2
        """,
        player_id,
        skill,
    )


async def add_inventory_item(
    player_id: str, item_id: str, quantity: int, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> None:
    _conn = conn or await db.get_pool()
    await _conn.execute(
        """
        INSERT INTO player_inventory (player_id, item_id, data)
        VALUES ($1, $2, $3::jsonb)
        ON CONFLICT (player_id, item_id)
        DO UPDATE SET data = jsonb_set(
            player_inventory.data,
            '{quantity}',
            (COALESCE((player_inventory.data->>'quantity')::int, 0) + $4)::text::jsonb
        )
        """,
        player_id,
        item_id,
        json.dumps({"quantity": quantity, "equipped": False}),
        quantity,
    )


async def remove_inventory_item(
    player_id: str, item_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> bool:
    _conn = conn or await db.get_pool()
    result = await _conn.execute(
        "DELETE FROM player_inventory WHERE player_id = $1 AND item_id = $2",
        player_id,
        item_id,
    )
    return result == "DELETE 1"


async def set_player_quest(
    player_id: str, quest_id: str, data: dict, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> None:
    _conn = conn or await db.get_pool()
    await _conn.execute(
        """
        INSERT INTO player_quests (player_id, quest_id, data)
        VALUES ($1, $2, $3::jsonb)
        ON CONFLICT (player_id, quest_id)
        DO UPDATE SET data = $3::jsonb
        """,
        player_id,
        quest_id,
        json.dumps(data),
    )


async def set_npc_disposition(
    npc_id: str,
    player_id: str,
    disposition: str,
    reason: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    _conn = conn or await db.get_pool()
    data = json.dumps({"disposition": disposition, "reason": reason})
    await _conn.execute(
        """
        INSERT INTO npc_dispositions (npc_id, player_id, data)
        VALUES ($1, $2, $3::jsonb)
        ON CONFLICT (npc_id, player_id)
        DO UPDATE SET data = $3::jsonb
        """,
        npc_id,
        player_id,
        data,
    )


async def save_combat_state(
    combat_id: str, data: dict, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> None:
    _conn = conn or await db.get_pool()
    await _conn.execute(
        """
        INSERT INTO combat_instances (combat_id, data)
        VALUES ($1, $2::jsonb)
        ON CONFLICT (combat_id) DO UPDATE SET data = $2::jsonb
        """,
        combat_id,
        json.dumps(data),
    )


async def delete_combat_state(combat_id: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None) -> None:
    _conn = conn or await db.get_pool()
    await _conn.execute("DELETE FROM combat_instances WHERE combat_id = $1", combat_id)


async def log_world_event(
    event_type: str, data: dict, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> None:
    _conn = conn or await db.get_pool()
    await _conn.execute(
        "INSERT INTO world_events_log (event_id, data) VALUES ($1, $2::jsonb)",
        event_type,
        json.dumps(data),
    )


# --- Map progress ---


async def upsert_map_progress(
    player_id: str,
    location_id: str,
    connections: list[str],
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Record a visited location. Idempotent — INSERT ON CONFLICT DO NOTHING."""
    _conn = conn or await db.get_pool()
    await _conn.execute(
        """
        INSERT INTO player_map_progress (player_id, location_id, data)
        VALUES ($1, $2, $3::jsonb)
        ON CONFLICT (player_id, location_id) DO NOTHING
        """,
        player_id,
        location_id,
        json.dumps({"connections": connections}),
    )


# --- Player flags ---


async def set_player_flag(
    player_id: str,
    flag: str,
    value: bool | str | int,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    _conn = conn or await db.get_pool()
    # Ensure 'flags' key exists, then set the specific flag
    await _conn.execute(
        """
        UPDATE players
        SET data = jsonb_set(
            CASE WHEN data ? 'flags' THEN data
                 ELSE jsonb_set(data, '{flags}', '{}'::jsonb)
            END,
            ARRAY['flags', $2],
            $3::jsonb
        )
        WHERE player_id = $1
        """,
        player_id,
        flag,
        json.dumps(value),
    )


# --- Session lifecycle ---


async def save_session_summary(
    player_id: str,
    session_id: str,
    summary_data: dict,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Persist a session summary to the session_summaries table."""
    _conn = conn or await db.get_pool()
    await _conn.execute(
        """
        INSERT INTO session_summaries (player_id, session_id, data)
        VALUES ($1, $2, $3::jsonb)
        """,
        player_id,
        session_id,
        json.dumps(summary_data),
    )


async def create_async_activity(player_id: str, activity_data: dict) -> str:
    """Create a new async activity. Returns the activity ID."""
    activity_id = f"activity_{uuid.uuid4().hex[:12]}"
    pool = await db.get_pool()
    await pool.execute(
        "INSERT INTO async_activities (id, player_id, data) VALUES ($1, $2, $3::jsonb)",
        activity_id,
        player_id,
        json.dumps(activity_data),
    )
    return activity_id


async def update_activity(
    activity_id: str, updates: dict, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> None:
    """Update specific fields in an activity's JSONB data."""
    _conn = conn or await db.get_pool()
    await _conn.execute(
        "UPDATE async_activities SET data = data || $2::jsonb WHERE id = $1",
        activity_id,
        json.dumps(updates),
    )


async def create_player(player_id: str, account_id: str | None, data: dict) -> None:
    """INSERT or update player. If a row already exists (e.g. from auth), update its data."""
    pool = await db.get_pool()
    await pool.execute(
        "INSERT INTO players (player_id, account_id, data) VALUES ($1, $2, $3::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data = EXCLUDED.data, updated_at = NOW()",
        player_id,
        account_id,
        json.dumps(data),
    )


async def update_player_portrait(
    player_id: str, portrait_url: str, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> None:
    """Store portrait_url in the player's JSONB data."""
    _conn = conn or await db.get_pool()
    await _conn.execute(
        """
        UPDATE players
        SET data = jsonb_set(data, '{portrait_url}', $2::jsonb)
        WHERE player_id = $1
        """,
        player_id,
        json.dumps(portrait_url),
    )


async def update_divine_favor(
    player_id: str, new_level: int, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> None:
    """Update divine_favor.level in player JSONB."""
    _conn = conn or await db.get_pool()
    await _conn.execute(
        """
        UPDATE players
        SET data = jsonb_set(data, '{divine_favor,level}', $2::jsonb)
        WHERE player_id = $1
        """,
        player_id,
        json.dumps(new_level),
    )


async def mark_favor_whisper_level(
    player_id: str, level: int, *, conn: asyncpg.Connection | asyncpg.Pool | None = None
) -> None:
    """Update divine_favor.last_whisper_level in player JSONB."""
    _conn = conn or await db.get_pool()
    await _conn.execute(
        """
        UPDATE players
        SET data = jsonb_set(data, '{divine_favor,last_whisper_level}', $2::jsonb)
        WHERE player_id = $1
        """,
        player_id,
        json.dumps(level),
    )


# --- God whispers ---


async def create_god_whisper(player_id: str, whisper_data: dict) -> str:
    """Insert a new god whisper. Returns the whisper ID."""
    whisper_id = f"whisper_{uuid.uuid4().hex[:12]}"
    pool = await db.get_pool()
    await pool.execute(
        "INSERT INTO god_whispers (id, player_id, data) VALUES ($1, $2, $3::jsonb)",
        whisper_id,
        player_id,
        json.dumps(whisper_data),
    )
    return whisper_id


async def mark_god_whisper_played(whisper_id: str) -> None:
    """Mark a god whisper as played."""
    pool = await db.get_pool()
    await pool.execute(
        """
        UPDATE god_whispers
        SET data = jsonb_set(data, '{status}', '"played"'::jsonb)
        WHERE id = $1
        """,
        whisper_id,
    )


# --- Story moments ---


async def save_story_moment(
    session_id: str,
    player_id: str,
    moment_key: str,
    description: str,
    template_id: str,
    asset_id: str | None,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Insert a story moment record."""
    _conn = conn or await db.get_pool()
    await _conn.execute(
        """
        INSERT INTO story_moments (session_id, player_id, moment_key, description, template_id, asset_id)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        session_id,
        player_id,
        moment_key,
        description,
        template_id,
        asset_id,
    )
