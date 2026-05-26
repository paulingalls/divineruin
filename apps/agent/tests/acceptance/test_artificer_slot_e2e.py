"""Real-DB E2E for the Artificer Portable-Lab training-slot borrow (story-006, AC#4).

The slot model lives in TS (slot_validation.ts) and the live craft path is the Bun
REST server. This proves end-to-end against one seeded testcontainer that:
  1. An Artificer who owns a Portable Lab, with a FULL crafting slot, can POST a second
     craft — it borrows the TRAINING slot and the row is stamped data.slot='training'.
  2. The borrow is COUNTED: a follow-on training POST is then rejected (training slot
     full) — the real-DB proof of the countActiveBySlot COALESCE fix (debt 95de7fa141df),
     which mocked bun tests cannot exercise.
  3. A non-Artificer with a full crafting slot is rejected (no exception).

Spawns `bun src/index.ts` against the migrated testcontainer (mirrors story-005's
test_crafting_resolution_gate_e2e.py + the capstone harness). Runs under
REQUIRE_DOCKER; skips cleanly when Docker is down.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
from acceptance._server import mint_server_jwt, start_server
from acceptance.seeds import seed_player

import db

FIELD_RECIPE = "wooden_club"  # workspace_required=field (always accessible), needs oak_wood
FIELD_RECIPE_MATERIAL = "oak_wood"
TRAINING_PROGRAM = "combat_basics"
PORTABLE_LAB_ITEM = "artificers_portable_lab"


@pytest.fixture(scope="module")
def slot_server(migrated_db: str) -> Iterator[dict[str, str]]:
    yield from start_server(migrated_db)


async def _seed_full_crafting_slot(pool, player_id: str) -> None:
    """Insert one in_progress crafting activity so the crafting slot is full."""
    data = {
        "status": "in_progress",
        "activity_type": "crafting",
        "parameters": {"recipe_id": FIELD_RECIPE},
    }
    await pool.execute(
        "INSERT INTO async_activities (id, player_id, data) VALUES ($1, $2, $3::jsonb) "
        "ON CONFLICT (id) DO UPDATE SET data = $3::jsonb",
        f"act_seed_{player_id}",
        player_id,
        json.dumps(data),
    )


async def _stock(pool, player_id: str, item_id: str, qty: int) -> None:
    await pool.execute(
        "INSERT INTO player_inventory (player_id, item_id, data) VALUES ($1, $2, $3::jsonb) "
        "ON CONFLICT (player_id, item_id) DO UPDATE SET data = $3::jsonb",
        player_id,
        item_id,
        json.dumps({"quantity": qty}),
    )


def _post(server: dict[str, str], player_id: str, body: dict) -> httpx.Response:
    return httpx.post(
        f"{server['base_url']}/api/activities",
        headers={"Authorization": f"Bearer {mint_server_jwt(player_id=player_id)}"},
        json=body,
        timeout=10.0,
    )


async def test_artificer_with_lab_borrows_training_slot_and_blocks_follow_on(
    slot_server: dict[str, str], reset_db_pool: str
) -> None:
    player_id = "player_artificer_e2e"
    pool = await db.get_pool()
    await seed_player(pool, player_id=player_id, class_="artificer")
    await pool.execute("DELETE FROM async_activities WHERE player_id = $1", player_id)
    await _stock(pool, player_id, PORTABLE_LAB_ITEM, 1)  # owns a Portable Lab
    await _stock(pool, player_id, FIELD_RECIPE_MATERIAL, 5)  # materials for the craft
    await _seed_full_crafting_slot(pool, player_id)  # crafting slot already full

    # The second craft borrows the training slot (crafting full + Artificer + lab).
    resp = _post(slot_server, player_id, {"type": "crafting", "parameters": {"recipe_id": FIELD_RECIPE}})
    assert resp.status_code == 200, resp.text
    activity_id = resp.json()["activity_id"]

    row = await pool.fetchrow("SELECT data FROM async_activities WHERE id = $1", activity_id)
    assert json.loads(row["data"])["slot"] == "training"

    # The borrow is counted: a training activity is now rejected (training slot full).
    train = _post(slot_server, player_id, {"type": "training", "parameters": {"program_id": TRAINING_PROGRAM}})
    assert train.status_code == 400, train.text
    assert "Training slot is full" in train.json()["error"]

    await pool.execute("DELETE FROM async_activities WHERE player_id = $1", player_id)
    await pool.execute("DELETE FROM player_inventory WHERE player_id = $1", player_id)


async def test_non_artificer_with_full_crafting_slot_is_rejected(
    slot_server: dict[str, str], reset_db_pool: str
) -> None:
    player_id = "player_nonartificer_e2e"
    pool = await db.get_pool()
    await seed_player(pool, player_id=player_id, class_="skirmisher")
    await pool.execute("DELETE FROM async_activities WHERE player_id = $1", player_id)
    await _stock(pool, player_id, FIELD_RECIPE_MATERIAL, 5)
    await _seed_full_crafting_slot(pool, player_id)

    resp = _post(slot_server, player_id, {"type": "crafting", "parameters": {"recipe_id": FIELD_RECIPE}})
    assert resp.status_code == 400, resp.text
    assert "Crafting slot is full" in resp.json()["error"]

    await pool.execute("DELETE FROM async_activities WHERE player_id = $1", player_id)
    await pool.execute("DELETE FROM player_inventory WHERE player_id = $1", player_id)
