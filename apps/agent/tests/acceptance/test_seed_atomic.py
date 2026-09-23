import asyncio
import json

import asyncpg
import pytest
from acceptance.test_creature_catalog import ROOT, seed_content


async def row_counts(dsn):
    conn = await asyncpg.connect(dsn)
    try:
        tables = set(seed_content.TABLE_MAP.values()) | {"player_map_progress"}
        return {table: await conn.fetchval(f"SELECT count(*) FROM {table}") for table in tables}
    finally:
        await conn.close()


@pytest.mark.parametrize("kind", ["creature", "gathering_node"])
def test_invalid_content_rolls_back_every_table(fresh_migrated_db, tmp_path, monkeypatch, capsys, kind):
    monkeypatch.setenv("DATABASE_URL", fresh_migrated_db)
    monkeypatch.setattr(seed_content, "CONTENT_DIR", tmp_path)
    for name in seed_content.TABLE_MAP:
        source = ROOT / "content" / name
        if source.exists():
            (tmp_path / name).write_bytes(source.read_bytes())
    if kind == "creature":
        path = tmp_path / "creatures.json"
        rows = json.loads(path.read_text())
        rows[0]["level"] = 8.0
        path.write_text(json.dumps(rows))
        expected = "hollow_shadeling: level: expected integer"
    else:
        path = tmp_path / "gathering_nodes.json"
        rows = json.loads(path.read_text())
        rows[0]["location_id"] = "missing_location"
        path.write_text(json.dumps(rows))
        expected = "unknown location_id 'missing_location'"
    with pytest.raises(SystemExit) as exit_info:
        asyncio.run(seed_content.main())
    assert exit_info.value.code != 0
    assert expected in capsys.readouterr().out
    assert all(count == 0 for count in asyncio.run(row_counts(fresh_migrated_db)).values())


def test_valid_seed_commits_creatures_and_map(fresh_migrated_db, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", fresh_migrated_db)
    asyncio.run(seed_content.main())
    counts = asyncio.run(row_counts(fresh_migrated_db))
    assert counts["creatures"] == len(json.loads((ROOT / "content/creatures.json").read_text()))

    async def seeded_creature_ids():
        conn = await asyncpg.connect(fresh_migrated_db)
        try:
            return {row["id"] for row in await conn.fetch("SELECT id FROM creatures")}
        finally:
            await conn.close()

    assert asyncio.run(seeded_creature_ids()) >= {
        "hollow_shadeling",
        "hollow_hollowmoth",
        "grey_wolf",
        "wild_boar",
        "giant_spider",
        "bandit",
        "thornveld_stalker",
        "corrupted_treant",
    }
    assert counts["player_map_progress"] > 0
