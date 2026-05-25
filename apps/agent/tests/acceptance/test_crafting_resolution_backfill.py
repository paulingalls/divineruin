"""Real-DB acceptance proof for migration 023 (story-005 resolution-gate backfill).

story-005 makes resolve_crafting fail loud (raise) when an in_progress crafting
activity lacks workspace_required / workspace_access / crafting_tier /
tainted_materials, and the worker reverts-and-reraises on that exception (infinite
retry). Activities created before story-005 — by either producer — predate those
keys, so migration 023 backfills them. This test seeds OLD-shape rows and runs the
migration's EXACT SQL against a real testcontainer, so the backfill can't silently
rot: editing 023's SQL re-runs here. Runs under REQUIRE_DOCKER; skips when Docker
is down.

The harness replays every migration at container init on empty tables (a no-op for
023), so — like the ops-runbook test — we seed first, then execute the migration
file's SQL directly to exercise the data transform.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from acceptance.seeds import seed_player

import db

_MIGRATION = Path(__file__).parents[4] / "scripts" / "migrations" / "023_backfill_crafting_resolution_params.sql"

# IDs this module inserts. The acceptance testcontainer is session-shared, so these
# rows must be torn down — in particular the MINIMAL recipe rows (they lack the full
# recipe shape and would make a later module's Bun server choke in loadRecipes()).
_TEST_RECIPE_IDS = ("forge_sword", "tainted_field_brew")
_TEST_ACTIVITY_IDS = ("act_forge", "act_tainted", "act_unskilled", "act_done", "act_errand")
_TEST_PLAYER_IDS = ("player_forge", "player_tainted", "player_unskilled", "player_terminal")


def _migration_sql() -> str:
    return _MIGRATION.read_text()


@pytest.fixture(autouse=True)
async def _cleanup_seeded_rows(reset_db_pool: str):
    """Delete this module's rows from the shared container after each test so the
    partial recipe rows don't leak into other acceptance modules (e.g. the capstone
    Bun server's loadRecipes). Players cascade to skill_advancement (migration 021)."""
    yield
    pool = await db.get_pool()
    await pool.execute("DELETE FROM async_activities WHERE id = ANY($1)", list(_TEST_ACTIVITY_IDS))
    await pool.execute("DELETE FROM recipes WHERE id = ANY($1)", list(_TEST_RECIPE_IDS))
    await pool.execute("DELETE FROM players WHERE player_id = ANY($1)", list(_TEST_PLAYER_IDS))


async def _seed_recipe(pool, recipe_id: str, *, workspace_required: str, tainted: bool) -> None:
    await pool.execute(
        "INSERT INTO recipes (id, data) VALUES ($1, $2::jsonb) ON CONFLICT (id) DO UPDATE SET data = $2::jsonb",
        recipe_id,
        json.dumps({"workspace_required": workspace_required, "tainted_materials": tainted}),
    )


async def _seed_crafting_activity(pool, activity_id: str, player_id: str, recipe_id: str, *, status: str) -> None:
    # OLD shape: parameters carry no resolution-gate keys (pre-story-005).
    data = {
        "status": status,
        "activity_type": "crafting",
        "parameters": {"recipe_id": recipe_id, "dc": 12},
        "outcome": None,
    }
    await pool.execute(
        "INSERT INTO async_activities (id, player_id, data) VALUES ($1, $2, $3::jsonb) "
        "ON CONFLICT (id) DO UPDATE SET data = $3::jsonb",
        activity_id,
        player_id,
        json.dumps(data),
    )


async def _params(pool, activity_id: str) -> dict:
    row = await pool.fetchrow("SELECT data FROM async_activities WHERE id = $1", activity_id)
    return json.loads(row["data"])["parameters"]


async def _seed_crafting_tier(pool, player_id: str, tier: str) -> None:
    await pool.execute(
        "INSERT INTO skill_advancement (player_id, skill_id, tier) VALUES ($1, 'crafting', $2) "
        "ON CONFLICT (player_id, skill_id) DO UPDATE SET tier = EXCLUDED.tier",
        player_id,
        tier,
    )


async def test_backfill_populates_gate_params_on_in_flight_crafting(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    await seed_player(pool, player_id="player_forge")
    # Expert crafter so crafting_tier backfills from the real skill row.
    await _seed_crafting_tier(pool, "player_forge", "expert")
    await _seed_recipe(pool, "forge_sword", workspace_required="forge", tainted=False)
    await _seed_crafting_activity(pool, "act_forge", "player_forge", "forge_sword", status="in_progress")

    await pool.execute(_migration_sql())

    params = await _params(pool, "act_forge")
    assert params["workspace_required"] == "forge"
    # Lenient backfill: {field, required}, sorted+deduped to match the producer shape.
    assert params["workspace_access"] == ["field", "forge"]
    assert params["crafting_tier"] == "expert"
    # tainted_materials must stay a JSON boolean, not the string "false".
    assert params["tainted_materials"] is False
    # Pre-existing keys survive the merge.
    assert params["recipe_id"] == "forge_sword"
    assert params["dc"] == 12


async def test_backfill_tainted_stays_json_boolean_and_field_dedups(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    await seed_player(pool, player_id="player_tainted")
    await _seed_crafting_tier(pool, "player_tainted", "master")
    await _seed_recipe(pool, "tainted_field_brew", workspace_required="field", tainted=True)
    await _seed_crafting_activity(pool, "act_tainted", "player_tainted", "tainted_field_brew", status="in_progress")

    await pool.execute(_migration_sql())

    params = await _params(pool, "act_tainted")
    assert params["tainted_materials"] is True
    # required == "field" must not produce ["field", "field"].
    assert params["workspace_access"] == ["field"]
    assert params["crafting_tier"] == "master"


async def test_backfill_defaults_crafting_tier_to_untrained_when_no_skill_row(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    await seed_player(pool, player_id="player_unskilled")
    # No skill_advancement row for this player.
    await _seed_recipe(pool, "forge_sword", workspace_required="forge", tainted=False)
    await _seed_crafting_activity(pool, "act_unskilled", "player_unskilled", "forge_sword", status="in_progress")

    await pool.execute(_migration_sql())

    params = await _params(pool, "act_unskilled")
    assert params["crafting_tier"] == "untrained"


async def test_backfill_leaves_non_crafting_and_terminal_rows_untouched(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    await seed_player(pool, player_id="player_terminal")
    await _seed_recipe(pool, "forge_sword", workspace_required="forge", tainted=False)
    # A resolved (terminal) crafting activity must NOT be rewritten.
    await _seed_crafting_activity(pool, "act_done", "player_terminal", "forge_sword", status="resolved")
    # A non-crafting in_progress activity must NOT be rewritten.
    await pool.execute(
        "INSERT INTO async_activities (id, player_id, data) VALUES ($1, $2, $3::jsonb)",
        "act_errand",
        "player_terminal",
        json.dumps(
            {
                "status": "in_progress",
                "activity_type": "companion_errand",
                "parameters": {"errand_type": "scout", "destination": "millhaven"},
            }
        ),
    )

    await pool.execute(_migration_sql())

    done = await _params(pool, "act_done")
    assert "workspace_required" not in done
    assert "workspace_access" not in done
    errand = await _params(pool, "act_errand")
    assert errand == {"errand_type": "scout", "destination": "millhaven"}
