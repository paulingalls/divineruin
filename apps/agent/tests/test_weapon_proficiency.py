import json
from pathlib import Path
from uuid import uuid4

import pytest

import db
from archetypes import parse_archetype_row
from creation_classes import CLASSES, STARTER_ITEM_IDS
from db_content_queries import get_item
from weapon_proficiency import has_weapon_proficiency

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = json.loads((ROOT / "packages/shared/fixtures/weapon_proficiency.json").read_text())
WEAPONS = [row for row in json.loads((ROOT / "content/items.json").read_text()) if row["type"] == "weapon"]
ARCHETYPES = json.loads((ROOT / "content/archetypes.json").read_text())


def mutate(row: dict, mutation: dict) -> dict:
    return {key: value for key, value in (row | mutation["set"]).items() if key not in mutation["delete"]}


@pytest.mark.parametrize("source", ["postgres", "valkey"])
@pytest.mark.parametrize("case", FIXTURE["malformed_weapons"])
async def test_invalid_weapon_read(dev_db_pool, monkeypatch, source: str, case: str) -> None:
    monkeypatch.setenv("CONTENT_CACHE_PREFIX", "")
    item_id = f"invalid_weapon_{uuid4().hex}"
    key = f"item:{item_id}"
    mutation = FIXTURE["malformed_weapons"][case]
    valid = WEAPONS[0] | FIXTURE["profiles"][WEAPONS[0]["id"]] | {"id": item_id}
    data = json.dumps(mutate(valid, mutation))
    match = rf"{item_id}.*{mutation['field']}"
    redis = await db.get_redis()
    try:
        if source == "valkey":
            await db._cache_set(key, data)
            assert await db._cache_get(key) == data
            with pytest.raises(ValueError, match=match):
                await get_item(item_id)
        else:
            async with dev_db_pool.acquire() as conn:
                transaction = conn.transaction()
                await transaction.start()
                try:
                    await conn.execute("INSERT INTO items (id, data) VALUES ($1, $2::jsonb)", item_id, data)
                    with pytest.raises(ValueError, match=match):
                        await get_item(item_id, conn=conn)
                    assert await db._cache_get(key) is None
                finally:
                    await transaction.rollback()
    finally:
        await redis.delete(key)


@pytest.mark.parametrize("case", FIXTURE["malformed_proficiencies"])
def test_invalid_proficiency_row(case: str) -> None:
    row = mutate(ARCHETYPES[0], FIXTURE["malformed_proficiencies"][case])
    with pytest.raises(ValueError, match=r"bad_archetype.*weapon_proficiencies"):
        parse_archetype_row("bad_archetype", row)


async def test_parsed_catalog_matches_complete_proficiency_table(dev_db_pool, monkeypatch) -> None:
    prefix = f"weapon_matrix:{uuid4().hex}:"
    monkeypatch.setenv("CONTENT_CACHE_PREFIX", prefix)
    expected_profiles = FIXTURE["profiles"]
    expected_proficiency = FIXTURE["proficiency"]
    assert sorted(row["id"] for row in WEAPONS) == sorted(expected_profiles)
    assert sorted(row["id"] for row in ARCHETYPES) == sorted(expected_proficiency)
    assert all("subtype" not in row for row in WEAPONS)
    archetypes = {row["id"]: parse_archetype_row(row["id"], row) for row in ARCHETYPES}
    redis = await db.get_redis()
    try:
        async with dev_db_pool.acquire() as conn:
            transaction = conn.transaction()
            await transaction.start()
            try:
                await conn.executemany(
                    """INSERT INTO items (id, data) VALUES ($1, $2::jsonb)
                    ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data""",
                    [(row["id"], json.dumps(row)) for row in WEAPONS],
                )
                items = {item_id: await get_item(item_id, conn=conn) for item_id in expected_profiles}
            finally:
                await transaction.rollback()
    finally:
        await redis.delete(*(f"{prefix}item:{item_id}" for item_id in expected_profiles))

    additions = FIXTURE["additions"]
    changed = set()
    for archetype_id, chassis in archetypes.items():
        tokens = chassis.weapon_proficiencies
        original = tokens
        if archetype_id in additions:
            token = additions[archetype_id]["token"]
            assert tokens.count(token) == 1
            original = tuple(t for t in tokens if t != token)
        expected = expected_proficiency[archetype_id]
        assert expected.keys() == items.keys()
        for item_id, item in items.items():
            assert item is not None
            assert {field: item[field] for field in expected_profiles[item_id]} == expected_profiles[item_id]
            proficient = has_weapon_proficiency(tokens, item)
            assert proficient is expected[item_id], (archetype_id, item_id)
            if proficient != has_weapon_proficiency(original, item):
                changed.add((archetype_id, item_id))
    assert changed == {(aid, addition["weapon"]) for aid, addition in additions.items()}


@pytest.mark.parametrize("archetype_id", CLASSES)
def test_starting_weapon_is_proficient(archetype_id: str) -> None:
    row = next(row for row in ARCHETYPES if row["id"] == archetype_id)
    chassis = parse_archetype_row(archetype_id, row)
    starter = STARTER_ITEM_IDS[CLASSES[archetype_id].starting_equipment["main_hand"]["name"]]
    item = next(item for item in WEAPONS if item["id"] == starter)
    assert has_weapon_proficiency(chassis.weapon_proficiencies, item), (archetype_id, starter)


@pytest.mark.parametrize("case", FIXTURE["token_cases"], ids=lambda case: case["token"])
def test_proficiency_tokens(case: dict) -> None:
    chassis = parse_archetype_row("token_case", ARCHETYPES[0] | {"weapon_proficiencies": [case["token"]]})
    assert has_weapon_proficiency(chassis.weapon_proficiencies, case["weapon"]) is case["expected"]
