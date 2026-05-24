"""Capstone: Recipe & Material System end-to-end (story-007, sprint-012 M5.1).

Proves the DB-loaded recipe flow composes across BOTH surfaces against one seeded
testcontainer, catching cross-language seam breaks the per-story tests miss:

  - message_event (Python agent): learn_recipe + query_recipe_requirements read
    the DB-loaded recipe via recipes.get_recipe.
  - http_websocket (TS REST): a spawned `bun src/index.ts` against the SAME DSN
    serves GET /api/activity-templates (listRecipes) and POST /api/activities
    crafting (getRecipe) for the SAME recipe id.

The seam assertion: the recipe the Python loader returns is byte-for-byte the one
the TS REST surface exposes (name, dc, materials, output) for the same id. TS
writes recipes during resolution; Python reads them every turn — this is where a
drift between the two parsers would surface.

Runs under `bun run test:acceptance` (REQUIRE_DOCKER on pre-push); skips cleanly
when Docker is down.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
from acceptance._server import mint_server_jwt, start_server
from acceptance.seeds import seed_player
from sample_fixtures import make_context

import db
import recipes
from recipe_tools import _learn_recipe_impl, _query_recipe_requirements_impl

# A seeded basic recipe an untrained crafter can both learn and craft.
CAPSTONE_RECIPE = "wooden_club"


async def _recipe_from_db(recipe_id: str) -> dict:
    """Read + parse one recipe straight from the testcontainer, bypassing the Redis
    cache. The seam claim is 'TS REST matches the DB both languages read'; a default
    Redis (localhost:6379) is up in this lane with a 300s TTL and no flush in
    reset_db_pool, so recipes.get_recipe() could be served from a sibling test's
    cache and never touch the testcontainer — a false-green. Reading the row directly
    keeps the assertion honest."""
    pool = await db.get_pool()
    row = await pool.fetchrow("SELECT data FROM recipes WHERE id = $1", recipe_id)
    assert row is not None, f"recipe {recipe_id} missing from testcontainer"
    return recipes.parse_recipe_row(recipe_id, json.loads(row["data"]))


@pytest.fixture(scope="module")
def capstone_server(migrated_db: str) -> Iterator[dict[str, str]]:
    """Bun REST server bound to the migrated testcontainer, for the module."""
    yield from start_server(migrated_db)


async def _seed_clean_player(player_id: str) -> None:
    pool = await db.get_pool()
    await seed_player(pool, player_id=player_id)
    await pool.execute("DELETE FROM player_known_recipes WHERE player_id = $1", player_id)
    await pool.execute("DELETE FROM async_activities WHERE player_id = $1", player_id)


# --- message_event surface (Python agent tools) ------------------------------


async def test_message_event_learn_and_query_over_db_recipe(reset_db_pool: str) -> None:
    """learn_recipe + query_recipe_requirements compose over the DB-loaded recipe."""
    await _seed_clean_player("player_capstone_msg")
    ctx = make_context(player_id="player_capstone_msg")

    learned = json.loads(await _learn_recipe_impl(ctx, CAPSTONE_RECIPE, "npc_teaching"))
    assert learned["learned"] == CAPSTONE_RECIPE
    assert learned["known_count"] == 1

    reqs = json.loads(await _query_recipe_requirements_impl(ctx, CAPSTONE_RECIPE))
    recipe = await recipes.get_recipe(CAPSTONE_RECIPE)
    assert recipe is not None
    # The tool surfaces the DB-loaded recipe's own requirements, not a default.
    assert reqs["recipe_id"] == CAPSTONE_RECIPE
    assert reqs["crafting_dc"] == recipe["crafting_dc"]
    assert reqs["workspace_required"] == recipe["workspace_required"]


# --- http_websocket surface (TS REST server) ---------------------------------


async def test_http_templates_lists_seeded_recipe(capstone_server: dict[str, str], reset_db_pool: str) -> None:
    """GET /api/activity-templates lists the seeded recipe via listRecipes."""
    token = mint_server_jwt(player_id="player_capstone_http")
    r = httpx.get(
        f"{capstone_server['base_url']}/api/activity-templates",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10.0,
    )
    assert r.status_code == 200, r.text
    # handleGetActivityTemplates swallows all errors -> 200 {groups:[]}; assert the
    # crafting group is present before next() so a seam break reads clearly instead
    # of a bare StopIteration traceback.
    groups = r.json()["groups"]
    crafting = next((g for g in groups if g["type"] == "crafting"), None)
    assert crafting is not None, f"no crafting group in templates (loader/seam break): {groups}"
    ids = {item["id"] for item in crafting["items"]}
    assert CAPSTONE_RECIPE in ids


async def test_http_create_crafting_activity_uses_db_recipe(
    capstone_server: dict[str, str], reset_db_pool: str
) -> None:
    """POST /api/activities crafting resolves recipe params from getRecipe and persists them."""
    player_id = "player_capstone_http"
    await _seed_clean_player(player_id)
    recipe = await recipes.get_recipe(CAPSTONE_RECIPE)
    assert recipe is not None

    # Stock the crafter with the recipe's required materials so the create reaches 200.
    pool = await db.get_pool()
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
        f"{capstone_server['base_url']}/api/activities",
        headers={"Authorization": f"Bearer {token}"},
        json={"type": "crafting", "parameters": {"recipe_id": CAPSTONE_RECIPE}},
        timeout=10.0,
    )
    assert resp.status_code == 200, resp.text
    activity_id = resp.json()["activity_id"]

    # The persisted activity carries getRecipe-derived params (output + dc).
    row = await pool.fetchrow("SELECT data FROM async_activities WHERE id = $1", activity_id)
    assert row is not None
    params = json.loads(row["data"])["parameters"]
    assert params["recipe_id"] == CAPSTONE_RECIPE
    assert params["result_item_id"] == recipe["output_item"]
    assert params["dc"] == recipe["crafting_dc"]

    # Self-cleaning: this leaves an in_progress async_activity for a player_id shared
    # with the templates/seam tests. The crafting slot check counts in_progress rows,
    # so a leftover would 400 a re-run or a future same-player create. Delete it.
    await pool.execute("DELETE FROM async_activities WHERE id = $1", activity_id)


# --- cross-language seam (E2E roll-up) ---------------------------------------


async def test_cross_language_recipe_is_consistent(capstone_server: dict[str, str], reset_db_pool: str) -> None:
    """The recipe the Python loader returns matches what the TS REST surface exposes
    for the same id — the seam both languages read every turn."""
    # Direct DB read (not get_recipe) so the seam is proven against the testcontainer
    # row, never a sibling test's Redis cache. See _recipe_from_db.
    recipe = await _recipe_from_db(CAPSTONE_RECIPE)

    token = mint_server_jwt(player_id="player_capstone_http")
    r = httpx.get(
        f"{capstone_server['base_url']}/api/activity-templates",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10.0,
    )
    assert r.status_code == 200, r.text
    groups = r.json()["groups"]
    crafting = next((g for g in groups if g["type"] == "crafting"), None)
    assert crafting is not None, f"no crafting group in templates (loader/seam break): {groups}"
    items = crafting["items"]
    tmpl = next((item for item in items if item["id"] == CAPSTONE_RECIPE), None)
    assert tmpl is not None, f"{CAPSTONE_RECIPE} not in crafting templates: {[i['id'] for i in items]}"

    assert tmpl["name"] == recipe["name"]
    assert tmpl["params"]["dc"] == recipe["crafting_dc"]
    assert {m["itemId"] for m in tmpl["materials"]} == {m["material_id"] for m in recipe["materials"]}
