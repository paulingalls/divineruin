"""Real-DB acceptance proof for recipe learning (story-006, AC5 E2E).

Migrates a Postgres testcontainer (migration 019) + seeds content, then drives
learn_recipe / query_recipe_requirements against it with the real db layer (no
injected mods). Proves the slot gate + player_known_recipes write work end-to-end
against the seeded recipe content + recipe_slots caps, not just under mocks. Runs
on pre-push under REQUIRE_DOCKER; skips cleanly when Docker is down.
"""

from __future__ import annotations

import json

import pytest
from acceptance.seeds import seed_player
from livekit.agents.llm import ToolError
from sample_fixtures import make_context

import db
from db_queries import count_player_known_recipes
from recipe_tools import _learn_recipe_impl, _query_recipe_requirements_impl

# Untrained crafters: cap 3, max recipe tier 'basic' (recipe_slots seed).
BASIC_RECIPES = ["wooden_club", "stone_tipped_spear", "bone_dagger", "oak_quarterstaff"]


async def _reset(pool, player_id: str) -> None:
    await pool.execute("DELETE FROM player_known_recipes WHERE player_id = $1", player_id)


async def test_learn_recipe_writes_player_known_recipe(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    await seed_player(pool, player_id="player_1")
    await _reset(pool, "player_1")

    ctx = make_context(player_id="player_1")
    result = json.loads(await _learn_recipe_impl(ctx, "wooden_club", "npc_teaching"))

    assert result["learned"] == "wooden_club"
    assert result["known_count"] == 1
    row = await pool.fetchrow(
        "SELECT learned_via FROM player_known_recipes WHERE player_id = $1 AND recipe_id = $2",
        "player_1",
        "wooden_club",
    )
    assert row is not None
    assert row["learned_via"] == "npc_teaching"
    assert await count_player_known_recipes("player_1") == 1


async def test_untrained_slot_cap_rejects_over_capacity(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    await seed_player(pool, player_id="player_cap")
    await _reset(pool, "player_cap")

    ctx = make_context(player_id="player_cap")
    # Untrained cap is 3 — the first three basic recipes learn cleanly.
    for recipe_id in BASIC_RECIPES[:3]:
        await _learn_recipe_impl(ctx, recipe_id, "discovery")
    # The fourth exceeds the cap.
    with pytest.raises(ToolError, match="slots full"):
        await _learn_recipe_impl(ctx, BASIC_RECIPES[3], "discovery")
    assert await count_player_known_recipes("player_cap") == 3


async def test_untrained_cannot_learn_trained_recipe(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    await seed_player(pool, player_id="player_tier")
    await _reset(pool, "player_tier")

    ctx = make_context(player_id="player_tier")
    # iron_sword is a 'trained' recipe; an untrained crafter is tier-ineligible.
    with pytest.raises(ToolError, match="too advanced"):
        await _learn_recipe_impl(ctx, "iron_sword", "npc_teaching")
    assert await count_player_known_recipes("player_tier") == 0


async def test_query_recipe_requirements_against_seeded_db(reset_db_pool: str) -> None:
    ctx = make_context(player_id="player_1")
    result = json.loads(await _query_recipe_requirements_impl(ctx, "iron_sword"))
    assert result["recipe_id"] == "iron_sword"
    assert isinstance(result["materials"], list)
    assert result["workspace_required"] in {"field", "workshop", "forge", "laboratory"}
    assert isinstance(result["crafting_dc"], int)
    assert isinstance(result["time"], str)
