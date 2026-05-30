"""Capstone — Milestone 3: Quality Outcomes & Experimentation (sprint-014, story-005).

Cross-cutting real-DB proof that M5.3's surfaces compose end-to-end against ONE seeded
testcontainer (migrations + content replayed by the acceptance conftest):

- Part A — story-002 (DB-loaded quality_outcomes) + story-003 (pure-margin 4-band
  resolve_crafting): the production orchestrator crafting_resolution.resolve_crafting_outcome
  fetches the recipe's category + that category's quality table FROM THE DB and threads it
  into the resolver. A seeded d20 forces each band; the attached bonus_property/flaw must be
  a row from the DB-loaded table (not a hardcoded fixture).
- Part B — story-003 + story-006: a crafting Failure resolves end-to-end THROUGH THE WORKER
  (async_worker._resolve_single_activity, real DB; only the LLM/TTS boundary mocked) and the
  player's hidden Crafting skill counter reads +1. Fulfills the deferred story-006 AC#4
  (decision crafting-counter-ac4-deferred). The tainted+sub-Expert path is a deterministic
  gate failure (no rng), and we assert the gate reason so a workspace-gate regression can't
  mask itself (the workspace gate is checked first).
- Part C — story-004 (experimentation, the message_event surface): experiment_with_materials
  against the real DB — a no-match consumes materials and records player_failed_experiments
  (migration 025) with no-match-only dedup, and a discoverable recipe is learned on success.

Runs under REQUIRE_DOCKER; skips cleanly when Docker is down.
"""

from __future__ import annotations

import json
import random
from unittest.mock import AsyncMock, patch

from acceptance.seeds import seed_player
from dice_seeds import seed_for_d20
from sample_fixtures import make_context

import db
import db_mutations
import db_queries
from async_worker import _resolve_single_activity
from crafting_resolution import resolve_crafting_outcome
from dialogue_parser import Segment
from experimentation_tools import _experiment_with_materials_impl
from quality_outcomes import get_quality_outcomes

# SAMPLE_PLAYER + PARAMS mirror test_async_rules.py: arcana modifier +3 and dc=11 make
# margin = d20 - 8, so d20 20/12/5/1 land in exceptional/success/partial/failure.
_PLAYER = {
    "level": 3,
    "attributes": {
        "strength": 14,
        "dexterity": 12,
        "constitution": 13,
        "intelligence": 10,
        "wisdom": 11,
        "charisma": 8,
    },
    "proficiencies": ["athletics", "arcana", "perception"],
    "inventory": [{"id": "iron_ingot", "name": "Iron Ingot"}, {"id": "leather_strip", "name": "Leather Strip"}],
}

_CRAFT_PARAMS = {
    "recipe_id": "iron_sword",
    "result_item_id": "iron_sword",
    "result_item_name": "Iron Sword",
    "required_materials": ["iron_ingot", "leather_strip"],
    "skill": "arcana",
    "dc": 11,
    "workspace_required": "forge",
    "workspace_access": ["field", "forge"],
    "crafting_tier": "expert",
    "tainted_materials": False,
}


async def _seed_inventory(pool, player_id: str, items: dict[str, int]) -> None:
    for item_id, qty in items.items():
        await pool.execute(
            """
            INSERT INTO player_inventory (player_id, item_id, data) VALUES ($1, $2, $3::jsonb)
            ON CONFLICT (player_id, item_id) DO UPDATE SET data = $3::jsonb
            """,
            player_id,
            item_id,
            json.dumps({"quantity": qty}),
        )


async def _resolved_activity_data(activity_id: str) -> dict:
    pool = await db.get_pool()
    row = await pool.fetchrow("SELECT data FROM async_activities WHERE id = $1", activity_id)
    return json.loads(row["data"])


# --- Part A: 4-band quality resolution composes with DB-loaded quality tables ---


async def test_four_bands_compose_with_db_quality_tables(reset_db_pool: str) -> None:
    """story-002 + story-003: each band resolves through the production orchestrator, and
    exceptional/partial draw their bonus_property/flaw from the testcontainer's quality row."""
    activity = {"activity_type": "crafting", "parameters": _CRAFT_PARAMS}
    # The DB-loaded weapon quality table (story-002) — the orchestrator reads this same row.
    weapon = await get_quality_outcomes("weapon")
    assert weapon is not None, "weapon quality_outcomes row must be seeded (story-002)"
    bonus_ids = {b["id"] for b in weapon["bonus_properties"]}
    flaw_ids = {f["id"] for f in weapon["flaws"]}

    exceptional = await resolve_crafting_outcome(activity, _PLAYER, rng=random.Random(seed_for_d20(20)))
    assert exceptional["tier"] == "exceptional"
    assert exceptional["bonus_property"]["id"] in bonus_ids
    assert exceptional["flaw"] is None

    success = await resolve_crafting_outcome(activity, _PLAYER, rng=random.Random(seed_for_d20(12)))
    assert success["tier"] == "success"
    assert success["bonus_property"] is None and success["flaw"] is None

    partial = await resolve_crafting_outcome(activity, _PLAYER, rng=random.Random(seed_for_d20(5)))
    assert partial["tier"] == "partial"
    assert partial["flaw"]["id"] in flaw_ids
    assert partial["bonus_property"] is None

    failure = await resolve_crafting_outcome(activity, _PLAYER, rng=random.Random(seed_for_d20(1)))
    assert failure["tier"] == "failure"
    assert failure["crafted_item_id"] is None
    assert failure["materials_consumed"] == ["iron_ingot", "leather_strip"]


# --- Part B: full-worker Failure -> hidden skill counter +1 (deferred story-006 AC#4) ---


async def test_worker_failure_increments_skill_counter_e2e(reset_db_pool: str) -> None:
    """story-003 + story-006: a crafting Failure resolved through the real worker bumps the
    hidden counter +1. Tainted materials + a sub-Expert crafter is a deterministic gate
    failure; workspace access is granted so the FAILURE is the tainted gate, asserted by reason."""
    pool = await db.get_pool()
    player_id = "player_m53_capstone_fail"
    await seed_player(pool, player_id=player_id)

    activity_data = {
        "status": "in_progress",
        "activity_type": "crafting",
        "parameters": {
            **_CRAFT_PARAMS,
            "crafting_tier": "trained",  # sub-Expert working tainted -> tainted_expert gate
            "tainted_materials": True,
            "workspace_access": ["field", "forge"],  # workspace gate (checked first) PASSES
        },
        "resolve_at": "2025-01-01T00:00:00Z",
    }
    activity_id = await db_mutations.create_async_activity(player_id, activity_data)

    assert await db_queries.get_crafting_skill_counter(player_id) == 0

    # Real DB claim/cache/increment/mark_resolved; only the LLM + TTS boundary is mocked.
    with (
        patch(
            "async_worker.generate_activity_narration",
            new_callable=AsyncMock,
            return_value=(
                [Segment("DM_NARRATOR", "grim", "The tainted ore fights you.")],
                "The tainted ore fights you.",
                "A ruined attempt.",
            ),
        ),
        patch("async_worker.synthesize_segments", new_callable=AsyncMock, return_value=f"{activity_id}.mp3"),
        patch("async_worker.generate_notification_hook", new_callable=AsyncMock, return_value="Your work failed."),
        patch("async_worker.send_push_notification", new_callable=AsyncMock),
    ):
        await _resolve_single_activity({"id": activity_id, "player_id": player_id, "activity_type": "crafting"})

    resolved = await _resolved_activity_data(activity_id)
    assert resolved["status"] == "resolved"
    assert resolved["outcome"]["tier"] == "failure"
    assert resolved["outcome"]["narrative_context"]["gate"] == "tainted_expert"
    assert await db_queries.get_crafting_skill_counter(player_id) == 1


# --- Part C: experimentation surface (story-004, message_event) ---


async def test_experimentation_no_match_records_and_dedups(reset_db_pool: str) -> None:
    """story-004: a no-match consumes materials + records player_failed_experiments; an
    identical retry short-circuits (already_tried) without consuming."""
    pool = await db.get_pool()
    player_id = "player_m53_capstone_exp"
    await seed_player(pool, player_id=player_id)
    await _seed_inventory(pool, player_id, {"iron_ingot": 5})
    ctx = make_context(player_id=player_id)

    first = json.loads(await _experiment_with_materials_impl(ctx, {"iron_ingot": 1}, "void_crown"))
    assert first["outcome"] == "no_match"
    assert first["consumed"] is True
    assert (
        await pool.fetchval(
            "SELECT COUNT(*) FROM player_failed_experiments WHERE player_id = $1 AND intended_output = $2",
            player_id,
            "void_crown",
        )
        == 1
    )

    second = json.loads(await _experiment_with_materials_impl(ctx, {"iron_ingot": 1}, "void_crown"))
    assert second["outcome"] == "already_tried"
    assert second["consumed"] is False
    # The dedup short-circuits BEFORE recording, so no duplicate row lands (no-match-only dedup).
    assert (
        await pool.fetchval(
            "SELECT COUNT(*) FROM player_failed_experiments WHERE player_id = $1 AND intended_output = $2",
            player_id,
            "void_crown",
        )
        == 1
    )


async def test_experimentation_success_learns_recipe(reset_db_pool: str) -> None:
    """story-004: discovering an unknown recipe from matching materials learns it
    (player_known_recipes, learned_via='experimentation')."""
    pool = await db.get_pool()
    player_id = "player_m53_capstone_learn"
    await seed_player(pool, player_id=player_id)
    await _seed_inventory(pool, player_id, {"iron_ingot": 5, "oak_wood": 3})
    ctx = make_context(player_id=player_id)

    out = json.loads(
        await _experiment_with_materials_impl(
            ctx, {"iron_ingot": 3, "oak_wood": 1}, "iron_sword", rng=random.Random(seed_for_d20(20))
        )
    )
    assert out["outcome"] == "success"
    assert out["learned_recipe"] == "iron_sword"
    row = await pool.fetchrow(
        "SELECT learned_via FROM player_known_recipes WHERE player_id = $1 AND recipe_id = $2",
        player_id,
        "iron_sword",
    )
    assert row is not None and row["learned_via"] == "experimentation"
