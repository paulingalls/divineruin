"""The REST producer allows sub-Expert tainted work; completion remains the tainted-material gate.
Rent a laboratory so workspace refusal cannot hide that gate. Call resolution directly to avoid LLM narration."""

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

# A seeded TAINTED laboratory recipe. The player rents a laboratory so the story-006
# workspace gate passes; being sub-Expert, the resolution tainted-Expert gate must fail.
TAINTED_LAB_RECIPE = "ward_stone"


@pytest.fixture(scope="module")
def gate_server(migrated_db: str) -> Iterator[dict[str, str]]:
    yield from start_server(migrated_db)


async def test_rest_created_tainted_craft_fails_the_expert_gate_at_resolution(
    gate_server: dict[str, str], reset_db_pool: str
) -> None:
    player_id = "player_gate_e2e"
    pool = await db.get_pool()
    # Default class; no skill_advancement row -> crafting tier captured as "untrained".
    await seed_player(pool, player_id=player_id, location_id="accord_guild_hall")
    await pool.execute("DELETE FROM async_activities WHERE player_id = $1", player_id)
    await pool.execute("DELETE FROM workspace_rentals WHERE player_id = $1", player_id)

    recipe = await recipes.get_recipe(TAINTED_LAB_RECIPE)
    assert recipe is not None
    assert recipe["workspace_required"] == "laboratory"
    assert recipe["tainted_materials"] is True

    # Rent a laboratory at the player's location so the story-006 workspace gate passes —
    # isolating the tainted-Expert gate as the thing resolution must catch.
    await pool.execute(
        """
        INSERT INTO workspace_rentals (id, player_id, location_id, workspace_type, source, expires_at)
        VALUES ($1, $2, 'accord_guild_hall', 'laboratory', 'rental', NULL)
        ON CONFLICT (id) DO NOTHING
        """,
        f"rental_{player_id}",
        player_id,
    )
    # Stock materials so the REST create reaches 200 (it checks materials + workspace + slot,
    # NOT recipe tier / tainted — those are the bypass this test exercises).
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

    resp = httpx.post(
        f"{gate_server['base_url']}/api/activities",
        headers={"Authorization": f"Bearer {mint_server_jwt(player_id=player_id)}"},
        json={"type": "crafting", "parameters": {"recipe_id": TAINTED_LAB_RECIPE}},
        timeout=10.0,
    )
    # Workspace gate passes (lab rented); no tainted gate at the REST layer -> created.
    assert resp.status_code == 200, resp.text
    activity_id = resp.json()["activity_id"]

    row = await pool.fetchrow("SELECT data FROM async_activities WHERE id = $1", activity_id)
    assert row is not None
    params = json.loads(row["data"])["parameters"]
    assert "laboratory" in params["workspace_access"]  # rental granted lab access
    assert params["crafting_tier"] == "untrained"  # sub-Expert
    assert params["tainted_materials"] is True

    # Resolution re-checks the captured tier against the tainted gate and FAILS the craft.
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
    assert outcome.narrative_context["gate"] == "tainted_expert"
    assert outcome.materials_returned == []

    await pool.execute("DELETE FROM async_activities WHERE player_id = $1", player_id)
    await pool.execute("DELETE FROM workspace_rentals WHERE player_id = $1", player_id)
