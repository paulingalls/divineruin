"""Capstone-style E2E for the story-005 resolution gates across both languages.

The live TS REST create path (handleCreateActivity) does NO workspace pre-flight, so
a player who lacks the required workspace can still START a craft. story-005 makes the
resolution boundary the chokepoint: the REST producer captures the player's REAL
accessible workspaces, and resolve_crafting (Python) re-checks them at completion and
fails the craft.

This proves the chokepoint end-to-end against one seeded testcontainer:
  1. A spawned `bun src/index.ts` serves POST /api/activities for a forge recipe to a
     player with only Field access (no forge rental) — the create succeeds (no gate).
  2. The persisted activity carries workspace_access == ["field"] — the TS producer
     captured the player's real, INSUFFICIENT access.
  3. resolve_crafting (the Python worker's resolver) reads those captured params and
     returns a `failure` outcome with the workspace gate — the bypass is caught.

resolve_crafting is called directly (not the full narration worker) so the proof needs
no LLM. Runs under `bun run test:acceptance` (REQUIRE_DOCKER on pre-push); skips when
Docker is down.
"""

from __future__ import annotations

import json
import random
from collections.abc import Iterator

import httpx
import pytest
from acceptance._server import mint_server_jwt, start_server
from acceptance.seeds import seed_player

import db
import recipes
from async_rules import resolve_crafting

# A seeded FORGE recipe — a clean player at the guild hall has no forge rental, so
# accessibleWorkspaceTier returns {field} and the resolution workspace gate must fail.
FORGE_RECIPE = "iron_sword"


@pytest.fixture(scope="module")
def gate_server(migrated_db: str) -> Iterator[dict[str, str]]:
    yield from start_server(migrated_db)


async def test_rest_created_craft_without_workspace_fails_the_gate_at_resolution(
    gate_server: dict[str, str], reset_db_pool: str
) -> None:
    player_id = "player_gate_e2e"
    pool = await db.get_pool()
    await seed_player(pool, player_id=player_id)
    await pool.execute("DELETE FROM async_activities WHERE player_id = $1", player_id)
    await pool.execute("DELETE FROM workspace_rentals WHERE player_id = $1", player_id)

    recipe = await recipes.get_recipe(FORGE_RECIPE)
    assert recipe is not None
    assert recipe["workspace_required"] == "forge"

    # Stock the recipe's materials so the REST create reaches 200 (it checks materials,
    # NOT workspace — that's the bypass this test exercises).
    for mat in recipe["materials"]:
        await pool.execute(
            """
            INSERT INTO player_inventory (player_id, item_id, data) VALUES ($1, $2, $3::jsonb)
            ON CONFLICT (player_id, item_id) DO UPDATE SET data = $3::jsonb
            """,
            player_id,
            mat["material_id"],
            json.dumps({"quantity": mat["quantity"] + 5}),
        )

    token = mint_server_jwt(player_id=player_id)
    resp = httpx.post(
        f"{gate_server['base_url']}/api/activities",
        headers={"Authorization": f"Bearer {token}"},
        json={"type": "crafting", "parameters": {"recipe_id": FORGE_RECIPE}},
        timeout=10.0,
    )
    # The REST path has no workspace gate, so the create SUCCEEDS despite no forge access.
    assert resp.status_code == 200, resp.text
    activity_id = resp.json()["activity_id"]

    row = await pool.fetchrow("SELECT data FROM async_activities WHERE id = $1", activity_id)
    assert row is not None
    params = json.loads(row["data"])["parameters"]
    # The TS producer captured the player's REAL access: Field only (no forge rental).
    assert params["workspace_access"] == ["field"]
    assert params["workspace_required"] == "forge"

    # Resolution re-checks the captured access and FAILS the craft — the chokepoint.
    # player_data is unused on the gate-fail path (it short-circuits before the roll).
    outcome = resolve_crafting(
        {},
        params,
        workspace_access=params["workspace_access"],
        crafting_tier=params["crafting_tier"],
        rng=random.Random(0),
    )
    assert outcome.tier == "failure"
    assert outcome.crafted_item_id is None
    assert outcome.narrative_context["gate"] == "workspace"
    assert outcome.materials_returned == []

    await pool.execute("DELETE FROM async_activities WHERE player_id = $1", player_id)
