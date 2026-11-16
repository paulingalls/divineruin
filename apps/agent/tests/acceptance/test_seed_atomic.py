import asyncio
import json
import uuid

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


@pytest.mark.parametrize("kind", ["creature", "gathering_node", "location_terrain", "production"])
def test_invalid_content_rolls_back_every_table(fresh_migrated_db, tmp_path, monkeypatch, capsys, kind):
    monkeypatch.setenv("DATABASE_URL", fresh_migrated_db)
    if kind == "production":
        monkeypatch.setenv("SEED_PRODUCTION", "1")
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
    elif kind == "location_terrain":
        path = tmp_path / "locations.json"
        rows = json.loads(path.read_text())
        invalid_rows = [row for row in rows if row["region_type"] == "city"][:5]
        invalid_rows[0].pop("terrain", None)
        for row, value in zip(invalid_rows[1:], ["unknown_terrain", "mountain", None, 42], strict=True):
            row["terrain"] = value
        path.write_text(json.dumps(rows))
        expected = invalid_rows[0]["id"]
    else:
        path = tmp_path / "gathering_nodes.json"
        rows = json.loads(path.read_text())
        rows[0]["location_id"] = "missing_location"
        path.write_text(json.dumps(rows))
        expected = "unknown location_id 'missing_location'"
    with pytest.raises(SystemExit) as exit_info:
        asyncio.run(seed_content.main())
    assert exit_info.value.code != 0
    output = capsys.readouterr().out
    assert expected in output
    if kind == "location_terrain":
        for row, fragments in zip(
            invalid_rows,
            [
                ("terrain", "None"),
                ("unknown_terrain",),
                ("mountain", "city", "wilderness"),
                ("terrain", "None"),
                ("terrain", "42"),
            ],
            strict=True,
        ):
            diagnostic = next(
                line for line in output.splitlines() if row["id"] in line and all(part in line for part in fragments)
            )
            assert diagnostic
    assert all(count == 0 for count in asyncio.run(row_counts(fresh_migrated_db)).values())


def test_valid_seed_commits_creatures_and_map(fresh_migrated_db, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", fresh_migrated_db)
    asyncio.run(seed_content.main())
    assert "default (fixtures enabled)" in capsys.readouterr().out
    snapshot = asyncio.run(rows(fresh_migrated_db))
    fixtures = json.loads((ROOT / "content/players.json").read_text())
    assert {r["player_id"] for r in snapshot["players"]} == {p["player_id"] for p in fixtures}
    assert {(r["player_id"], r["location_id"]) for r in snapshot["player_map_progress"]} == {
        (p["player_id"], p["location_id"]) for p in fixtures
    }
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

    async def seeded_locations():
        conn = await asyncpg.connect(fresh_migrated_db)
        try:
            return {
                row["id"]: json.loads(row["data"])["terrain"]
                for row in await conn.fetch("SELECT id, data FROM locations")
            }
        finally:
            await conn.close()

    expected = {row["id"]: row["terrain"] for row in json.loads((ROOT / "content/locations.json").read_text())}
    assert asyncio.run(seeded_locations()) == expected
    before = asyncio.run(rows(fresh_migrated_db))
    asyncio.run(seed_content.main())
    assert asyncio.run(rows(fresh_migrated_db)) == before
    asyncio.run(
        rows(
            fresh_migrated_db,
            """
        UPDATE gathering_nodes SET data = data || '{"quantity":0,"discovered":true}';
    """,
        )
    )
    asyncio.run(seed_content.main())
    assert [r["data"] for r in asyncio.run(rows(fresh_migrated_db))["gathering_nodes"]] == [
        r["data"] for r in before["gathering_nodes"]
    ]


@pytest.fixture(autouse=True)
def default_mode(monkeypatch):
    monkeypatch.delenv("SEED_PRODUCTION", raising=False)
    monkeypatch.setenv("CONTENT_CACHE_PREFIX", "seed-atomic-" + uuid.uuid4().hex + ":")


async def rows(dsn, sql=None):
    conn = await asyncpg.connect(dsn)
    try:
        if sql:
            await conn.execute(sql)
        return {
            table: [
                json.loads(r["row"])
                for r in await conn.fetch(
                    f"SELECT row_to_json(t)::text AS row FROM {table} t ORDER BY row_to_json(t)::text"
                )
            ]
            for table in set(seed_content.TABLE_MAP.values()) | {"player_map_progress"}
        }
    finally:
        await conn.close()


def test_production_reseed_preserves_rows_and_deploys_authored_edits(fresh_migrated_db, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", fresh_migrated_db)
    monkeypatch.setenv("SEED_PRODUCTION", "1")
    asyncio.run(seed_content.main())
    assert "production" in capsys.readouterr().out
    initial = asyncio.run(rows(fresh_migrated_db))
    assert initial["creatures"] and initial["locations"] and initial["gathering_nodes"]
    assert initial["players"] == initial["player_map_progress"] == []
    before = asyncio.run(
        rows(
            fresh_migrated_db,
            """
        INSERT INTO players (player_id, data) VALUES ('live_player', '{"name":"Live","level":3}');
        INSERT INTO player_map_progress (player_id, location_id, data)
        VALUES ('live_player', 'accord_guild_hall', '{"connections":["live"]}');
        UPDATE gathering_nodes SET data = data || '{"quantity":0,"discovered":true}';
    """,
        )
    )
    asyncio.run(seed_content.main())
    assert asyncio.run(rows(fresh_migrated_db)) == before
    location = before["locations"][0]
    node = before["gathering_nodes"][0]
    asyncio.run(
        rows(
            fresh_migrated_db,
            f"""
        UPDATE locations SET data = data || '{{"description":"stale"}}' WHERE id = '{location["id"]}';
        UPDATE gathering_nodes SET data = data || '{{"respawn_days":999}}' WHERE id = '{node["id"]}';
    """,
        )
    )
    asyncio.run(seed_content.main())
    after = asyncio.run(rows(fresh_migrated_db))
    # Authored changes deploy while the node's depleted quantity and discovery survive.
    for actual, original in zip(after["locations"], before["locations"], strict=True):
        if actual["id"] == location["id"]:
            assert actual["data"] == original["data"]
        else:
            assert actual == original
    for table in before.keys() - {"locations", "gathering_nodes"}:
        assert after[table] == before[table]
    for actual, original in zip(after["gathering_nodes"], before["gathering_nodes"], strict=True):
        assert actual["data"] == original["data"]
        if actual["id"] != node["id"]:
            assert actual == original


@pytest.mark.parametrize("contamination", ["players", "progress"])
def test_production_refuses_named_fixtures_atomically(fresh_migrated_db, tmp_path, monkeypatch, capsys, contamination):
    monkeypatch.setenv("DATABASE_URL", fresh_migrated_db)
    for name in seed_content.TABLE_MAP:
        (tmp_path / name).write_bytes((ROOT / "content" / name).read_bytes())
    fixtures = json.loads((tmp_path / "players.json").read_text())
    fixtures.append(dict(fixtures[0], player_id="second_fixture"))
    (tmp_path / "players.json").write_text(json.dumps(fixtures))
    monkeypatch.setattr(seed_content, "CONTENT_DIR", tmp_path)
    asyncio.run(seed_content.main())
    if contamination == "progress":
        asyncio.run(
            rows(
                fresh_migrated_db,
                """
            ALTER TABLE player_map_progress DROP CONSTRAINT fk_player_map_progress_player;
            DELETE FROM players;
        """,
            )
        )
    before = asyncio.run(rows(fresh_migrated_db))
    capsys.readouterr()
    monkeypatch.setenv("SEED_PRODUCTION", "1")
    with pytest.raises(SystemExit) as refusal:
        asyncio.run(seed_content.main())
    assert refusal.value.code != 0
    output = capsys.readouterr().out
    assert "fixture" in output
    assert all(p["player_id"] in output for p in fixtures)
    assert asyncio.run(rows(fresh_migrated_db)) == before


def test_invalid_production_switch_refuses(monkeypatch):
    monkeypatch.setenv("SEED_PRODUCTION", "true")
    with pytest.raises(ValueError, match="SEED_PRODUCTION"):
        asyncio.run(seed_content.main())


@pytest.mark.parametrize("fixtures", [None, [], [{"player_id": ""}]])
def test_production_requires_fixture_inventory(fresh_migrated_db, tmp_path, monkeypatch, capsys, fixtures):
    monkeypatch.setenv("DATABASE_URL", fresh_migrated_db)
    monkeypatch.setenv("SEED_PRODUCTION", "1")
    monkeypatch.setattr(seed_content, "CONTENT_DIR", tmp_path)
    if fixtures is not None:
        (tmp_path / "players.json").write_text(json.dumps(fixtures))
    with pytest.raises(SystemExit):
        asyncio.run(seed_content.main())
    assert "players.json: expected nonempty fixture corpus with valid player ids" in capsys.readouterr().out
    assert all(count == 0 for count in asyncio.run(row_counts(fresh_migrated_db)).values())
