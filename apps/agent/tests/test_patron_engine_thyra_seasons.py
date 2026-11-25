from pathlib import Path
from uuid import uuid4

import pytest

import world_season

MIGRATIONS = Path(__file__).resolve().parents[3] / "scripts" / "migrations"


@pytest.mark.parametrize("upgrade", [False, True])
async def test_world_season_migration(dev_db_pool, upgrade):
    files = sorted(MIGRATIONS.glob("*.sql"))
    season_migration = MIGRATIONS / "066_world_season.sql"
    schema = f"season_{uuid4().hex}"
    async with dev_db_pool.acquire() as conn:
        transaction = conn.transaction()
        await transaction.start()
        try:
            await conn.execute(f'CREATE SCHEMA "{schema}"')
            await conn.execute(f'SET LOCAL search_path TO "{schema}"')
            for path in files:
                if upgrade and path == season_migration:
                    with pytest.raises(ValueError, match="season"):
                        await world_season.current_season(conn=conn)
                    await conn.execute("INSERT INTO world_flags (flag_name, data) VALUES ('unrelated', '{}')")
                await conn.execute(path.read_text())
            assert await world_season.current_season(conn=conn) == "spring"
            if upgrade:
                assert await conn.fetchval("SELECT data::text FROM world_flags WHERE flag_name = 'unrelated'") == "{}"
            for season in ("summer", "autumn", "winter", "spring"):
                await conn.execute(
                    "UPDATE world_flags SET data = jsonb_build_object('value', $1::text) WHERE flag_name = 'season'",
                    season,
                )
                assert await world_season.current_season(conn=conn) == season
            for invalid in ("{}", '{"value":null}', '{"value":"monsoon"}'):
                await conn.execute("UPDATE world_flags SET data = $1::jsonb WHERE flag_name = 'season'", invalid)
                with pytest.raises(ValueError, match="season"):
                    await world_season.current_season(conn=conn)
            await conn.execute("DELETE FROM world_flags WHERE flag_name = 'season'")
            with pytest.raises(ValueError, match="season"):
                await world_season.current_season(conn=conn)
        finally:
            await transaction.rollback()
