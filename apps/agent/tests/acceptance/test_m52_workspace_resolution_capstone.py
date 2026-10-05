"""Both languages must execute the expires_at predicate against the same rows; a mocked query cannot prove the timestamp/NULL arms."""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
from acceptance._server import mint_server_jwt, start_server
from acceptance.seeds import seed_player
from sample_fixtures import make_context

import db
from crafting_tools import _query_available_workspaces_impl, _rent_workspace_impl

# A forge recipe an untrained crafter can still CREATE (the REST create gate checks
# workspace access only; crafting tier is captured for resolution, not gated here).
CAPSTONE_RECIPE = "iron_shield"  # forge | iron_ingot x2 + leather_strip x1
CAPSTONE_LOCATION = "millhaven"

# The authored accord_forge row hosts both bundle workspace tags, and
# grimjaw_blacksmith's schedule puts the rentable NPC there.
BUNDLE_LOCATION = "accord_forge"
BUNDLE_NPC = "grimjaw_blacksmith"


@pytest.fixture(scope="module")
def capstone_server(migrated_db: str) -> Iterator[dict[str, str]]:
    """Bun REST server bound to the migrated testcontainer, for the module."""
    yield from start_server(migrated_db)


async def _seed_forge_crafter(player_id: str) -> None:
    """Seed a player at CAPSTONE_LOCATION stocked with the recipe's materials, with a
    clean slate (no leftover rentals or activities from a sibling test)."""
    pool = await db.get_pool()
    await seed_player(pool, player_id=player_id, location_id=CAPSTONE_LOCATION)
    await pool.execute("DELETE FROM workspace_rentals WHERE player_id = $1", player_id)
    await pool.execute("DELETE FROM async_activities WHERE player_id = $1", player_id)
    for item_id, qty in (("iron_ingot", 2), ("leather_strip", 1)):
        await pool.execute(
            """
            INSERT INTO player_inventory (player_id, item_id, data) VALUES ($1, $2, $3::jsonb)
            ON CONFLICT (player_id, item_id) DO UPDATE SET data = $3::jsonb
            """,
            player_id,
            item_id,
            json.dumps({"quantity": qty}),
        )


async def _set_forge_rental(player_id: str, *, expires_sql: str) -> None:
    """Replace the player's rentals with a single forge rental whose expiry is given by
    a static SQL fragment (NULL standing / past / future). DELETE-first because
    workspace_rentals appends history (surrogate id PK), so a stale active row would mask
    the predicate under test."""
    pool = await db.get_pool()
    await pool.execute("DELETE FROM workspace_rentals WHERE player_id = $1", player_id)
    await pool.execute(
        f"""
        INSERT INTO workspace_rentals (id, player_id, location_id, workspace_type, source, expires_at)
        VALUES ($1, $2, $3, 'forge', 'rental', {expires_sql})
        """,
        f"wr_{player_id}",
        player_id,
        CAPSTONE_LOCATION,
    )


def _post_craft(server: dict[str, str], player_id: str) -> httpx.Response:
    token = mint_server_jwt(player_id=player_id)
    return httpx.post(
        f"{server['base_url']}/api/activities",
        headers={"Authorization": f"Bearer {token}"},
        json={"type": "crafting", "parameters": {"recipe_id": CAPSTONE_RECIPE}},
        timeout=10.0,
    )


# --- http_websocket surface: the REST workspace gate over the real expires_at predicate ---


async def test_rest_create_rejected_when_forge_rental_expired(
    capstone_server: dict[str, str], reset_db_pool: str
) -> None:
    player_id = "player_capstone_expired"
    await _seed_forge_crafter(player_id)
    await _set_forge_rental(player_id, expires_sql="NOW() - INTERVAL '1 hour'")

    resp = _post_craft(capstone_server, player_id)
    assert resp.status_code == 400, resp.text
    assert "no access to a forge workspace" in resp.json()["error"]

    # Gate rejected before the txn: no activity row, materials untouched.
    pool = await db.get_pool()
    count = await pool.fetchval("SELECT COUNT(*) FROM async_activities WHERE player_id = $1", player_id)
    assert count == 0


async def test_rest_create_allowed_when_forge_rental_active(
    capstone_server: dict[str, str], reset_db_pool: str
) -> None:
    player_id = "player_capstone_active"
    await _seed_forge_crafter(player_id)
    await _set_forge_rental(player_id, expires_sql="NOW() + INTERVAL '1 day'")

    resp = _post_craft(capstone_server, player_id)
    assert resp.status_code == 200, resp.text
    activity_id = resp.json()["activity_id"]

    pool = await db.get_pool()
    row = await pool.fetchrow("SELECT data FROM async_activities WHERE id = $1", activity_id)
    assert row is not None
    params = json.loads(row["data"])["parameters"]
    assert params["workspace_required"] == "forge"
    assert "forge" in params["workspace_access"]


async def test_rest_create_allowed_with_standing_rental(capstone_server: dict[str, str], reset_db_pool: str) -> None:
    player_id = "player_capstone_standing"
    await _seed_forge_crafter(player_id)
    await _set_forge_rental(player_id, expires_sql="NULL")

    resp = _post_craft(capstone_server, player_id)
    assert resp.status_code == 200, resp.text


# --- message_event surface: the Python tool reads the same predicate, same rows ---


async def test_message_event_query_workspaces_honors_expiry(reset_db_pool: str) -> None:
    # M52-namespaced player id: the M5.1 capstone reuses "player_capstone_msg"; a
    # distinct id keeps the two capstones isolated if the acceptance lane ever
    # parallelizes (pytest-xdist is installed; test:python already runs -n 4).
    player_id = "player_capstone_m52_msg"
    await _seed_forge_crafter(player_id)
    ctx = make_context(player_id=player_id, location_id=CAPSTONE_LOCATION)

    await _set_forge_rental(player_id, expires_sql="NOW() - INTERVAL '1 hour'")
    expired = json.loads(await _query_available_workspaces_impl(ctx))
    assert "forge" not in expired["accessible"], expired
    assert "field" in expired["accessible"]  # field floor is always present

    await _set_forge_rental(player_id, expires_sql="NOW() + INTERVAL '1 day'")
    active = json.loads(await _query_available_workspaces_impl(ctx))
    assert "forge" in active["accessible"], active


# --- the bundle write, read back by BOTH languages (story-015 AC3) ---


async def test_python_bundle_rental_is_read_by_the_ts_gate_as_forge_access(
    capstone_server: dict[str, str], reset_db_pool: str
) -> None:
    """Write through Python and read through the TS gate; separately mocked halves would accept an invalid bundle row vocabulary."""
    player_id = "player_capstone_m52_bundle"
    pool = await db.get_pool()
    await _seed_forge_crafter(player_id)
    await pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{location_id}', $2::jsonb) || jsonb_build_object('gold', 5.0) "
        "WHERE player_id = $1",
        player_id,
        json.dumps(BUNDLE_LOCATION),
    )
    await (await db.get_redis()).delete(f"location:{BUNDLE_LOCATION}")

    rental = json.loads(
        await _rent_workspace_impl(
            make_context(player_id=player_id, location_id=BUNDLE_LOCATION), "forge_laboratory", BUNDLE_NPC, 1
        )
    )
    assert rental["price_sp"] == 12.0, rental

    rows = await pool.fetch(
        "SELECT workspace_type FROM workspace_rentals WHERE player_id = $1 ORDER BY workspace_type", player_id
    )
    assert [row["workspace_type"] for row in rows] == ["forge", "laboratory"]

    # The load-bearing half: the TS crafting gate re-parses those rows.
    resp = _post_craft(capstone_server, player_id)
    assert resp.status_code == 200, resp.text
    assert (
        "forge"
        in json.loads(
            (await pool.fetchrow("SELECT data FROM async_activities WHERE id = $1", resp.json()["activity_id"]))["data"]
        )["parameters"]["workspace_access"]
    )
