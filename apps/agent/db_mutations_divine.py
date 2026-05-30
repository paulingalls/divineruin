"""Divine-favor, god-whisper, and story-moment write operations.

Extracted from db_mutations.py (file-size touch-split, debt 1f235ab5066a) to bring
db_mutations.py back under the 500-line cap. All async, accept optional conn where
they participate in a caller transaction.
"""

import json
import uuid

import asyncpg

import db


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
