"""Use an isolated acceptance database: global legacy-key removal would corrupt a shared database's concurrent tests."""

from __future__ import annotations

import json
from pathlib import Path

import db

_MIGRATION_057 = Path(__file__).resolve().parents[4] / "scripts" / "migrations" / "057_veil_ward_scope.sql"


async def _insert_player(pool, player_id: str, data: dict) -> None:
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
        player_id,
        json.dumps(data),
    )


async def _has_ward_key(pool, player_id: str) -> bool:
    return await pool.fetchval("SELECT data ? 'veil_ward' FROM players WHERE player_id = $1", player_id)


async def test_migration_057_creates_veil_wards_table(reset_db_pool: str) -> None:
    pool = await db.get_pool()

    assert await pool.fetchval("SELECT to_regclass('public.veil_wards')") is not None

    columns = {
        r["column_name"]: r["is_nullable"]
        for r in await pool.fetch(
            "SELECT column_name, is_nullable FROM information_schema.columns WHERE table_name = 'veil_wards'"
        )
    }
    assert set(columns) == {"ward_id", "scope_kind", "scope_id", "source", "expires_at", "dismissible", "created_at"}
    # expires_at NULL means "no absolute expiry"; dismissible is orthogonal and never NULL.
    assert columns["expires_at"] == "YES"
    assert columns["dismissible"] == "NO"

    # The scope key is a LOOKUP index, deliberately NOT unique: many wards may cover one scope
    # (a 1h Artificer anchor must not overwrite a permanent Sacred-site ward). Decision 4e126734aebe.
    index = await pool.fetchrow(
        "SELECT indexdef FROM pg_indexes WHERE tablename = 'veil_wards' AND indexname = 'idx_veil_wards_scope'"
    )
    assert index is not None, "idx_veil_wards_scope missing"
    assert "UNIQUE" not in index["indexdef"].upper()


async def test_migration_057_drops_legacy_veil_ward_key(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    # Pre-057 states: a player carrying the migration-045 key beside siblings, and one without it.
    await _insert_player(
        pool,
        "mig057_warded",
        {"name": "Cleric", "veil_ward": {"active": True, "source": "cleric"}, "resonance": {"current": 7}},
    )
    await _insert_player(pool, "mig057_plain", {"name": "Rogue", "resonance": {"current": 3}})

    assert await _has_ward_key(pool, "mig057_warded") is True

    await pool.execute(_MIGRATION_057.read_text())

    # The key is gone...
    assert await _has_ward_key(pool, "mig057_warded") is False
    # ...its siblings survive (a targeted `data - 'veil_ward'`, not a data replace)...
    assert (
        await pool.fetchval("SELECT data->'resonance'->>'current' FROM players WHERE player_id = $1", "mig057_warded")
        == "7"
    )
    # ...and a row that never had the key is unharmed.
    assert await _has_ward_key(pool, "mig057_plain") is False
    assert (
        await pool.fetchval("SELECT data->'resonance'->>'current' FROM players WHERE player_id = $1", "mig057_plain")
        == "3"
    )


async def test_migration_057_is_idempotent(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    await _insert_player(pool, "mig057_twice", {"name": "Druid", "veil_ward": {"active": False, "source": None}})

    await pool.execute(_MIGRATION_057.read_text())
    assert await _has_ward_key(pool, "mig057_twice") is False

    # Re-running must not raise (CREATE TABLE/INDEX IF NOT EXISTS) and must not change the row.
    await pool.execute(_MIGRATION_057.read_text())
    assert await _has_ward_key(pool, "mig057_twice") is False
    assert await pool.fetchval("SELECT data->>'name' FROM players WHERE player_id = $1", "mig057_twice") == "Druid"
