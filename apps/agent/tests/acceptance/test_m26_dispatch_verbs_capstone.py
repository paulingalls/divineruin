from __future__ import annotations

import json
import uuid

from acceptance.seeds import seed_async_activity, seed_player, seed_training_activity
from sample_fixtures import make_context

import db
import db_training
from activity_tools import _begin_activity_impl, _resolve_activity_impl
from blacksmith_agent import BLACKSMITH_TOOLS
from combat_agent import COMBAT_AGENT_TOOLS
from creation_agent import CREATION_TOOLS
from dispatch_agent import DISPATCH_TOOLS
from exploration_agent import EXPLORATION_TOOLS
from llm_config import MAX_STRICT_TOOLS
from onboarding_agent import ONBOARDING_TOOLS
from query_tools import _query_info_impl

_FOLDED_NOUNS = frozenset(
    {
        "initiate_training_cycle",
        "resolve_training_midpoint",
        "query_training_programs",
        "dispatch_companion_errand",
        "resolve_companion_errand",
        "start_crafting_project",
        "rent_workspace",
        "query_available_workspaces",
        "experiment_with_materials",
        "query_recipe_requirements",
    }
)

_ALL_AGENT_TOOLS = {
    "combat": COMBAT_AGENT_TOOLS,
    "exploration": EXPLORATION_TOOLS,
    "dispatch": DISPATCH_TOOLS,
    "onboarding": ONBOARDING_TOOLS,
    "creation": CREATION_TOOLS,
    "blacksmith": BLACKSMITH_TOOLS,
}

# query_info is NOT wired onto creation_agent (character creation has no world-query
# surface); it is present on the other five. Derived empirically (grep -l 'query_info'
# apps/agent/*_agent.py), not guessed.
_QUERY_INFO_CARRIERS = {"combat", "exploration", "dispatch", "onboarding", "blacksmith"}


def test_dispatch_verbs_registered_and_folded_nouns_gone_everywhere() -> None:
    assert any(t.__name__ == "begin_activity" for t in DISPATCH_TOOLS)
    assert any(t.__name__ == "resolve_activity" for t in DISPATCH_TOOLS)

    for agent_name, tools in _ALL_AGENT_TOOLS.items():
        names = {t.__name__ for t in tools}
        if agent_name != "dispatch":
            assert "begin_activity" not in names, f"{agent_name} must not register begin_activity"
            assert "resolve_activity" not in names, f"{agent_name} must not register resolve_activity"

        has_query_info = "query_info" in names
        assert has_query_info == (agent_name in _QUERY_INFO_CARRIERS), (
            f"query_info presence on {agent_name} does not match the expected carrier set"
        )

        leaked = names & _FOLDED_NOUNS
        assert not leaked, f"{agent_name} still registers folded nouns: {leaked}"


def test_tool_budget_holds_exact_count() -> None:
    """Exact registration counts make a tool addition deliberate even below the vendor ceiling."""
    assert len(DISPATCH_TOOLS) == 9
    assert len(DISPATCH_TOOLS) <= MAX_STRICT_TOOLS


# --- begin_activity: one routed kind per test, against real PG -----------------------


async def test_begin_activity_training_creates_a_real_training_activity_row(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    player_id = "cap_m26_begin_training"
    try:
        await seed_player(pool, player_id=player_id)

        raw = await _begin_activity_impl(make_context(player_id), "training", program_id="combat_basics")
        result = json.loads(raw)

        rows = await db_training.get_player_training_activities(player_id, conn=pool)
        assert len(rows) == 1
        assert rows[0]["id"] == result["activity_id"]
        assert rows[0]["state"] == "running_first_half"
        assert rows[0]["data"]["program_id"] == "combat_basics"
    finally:
        await pool.execute("DELETE FROM training_activities WHERE player_id = $1", player_id)
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)


async def test_begin_activity_companion_errand_creates_an_async_activity_row(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    player_id = "cap_m26_begin_errand"
    try:
        # Dispatch gates on the ASSIGNED companion (the archetype's complement), so the
        # seeded class must be one Kael complements or begin_activity refuses the id below.
        await seed_player(pool, player_id=player_id, class_="mage")

        raw = await _begin_activity_impl(
            make_context(player_id),
            "companion_errand",
            companion_id="companion_kael",
            errand_type="scout",
            destination="millhaven",
        )
        result = json.loads(raw)

        row = await pool.fetchrow("SELECT data FROM async_activities WHERE id = $1", result["activity_id"])
        assert row is not None
        data = json.loads(row["data"])
        assert data["status"] == "in_progress"
        assert data["activity_type"] == "companion_errand"
        assert data["parameters"] == {"errand_type": "scout", "destination": "millhaven"}
    finally:
        await pool.execute("DELETE FROM async_activities WHERE player_id = $1", player_id)
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)


async def test_begin_activity_crafting_creates_an_in_progress_crafting_activity(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    player_id = "cap_m26_begin_crafting"
    try:
        await seed_player(pool, player_id=player_id)
        await pool.execute(
            "INSERT INTO player_known_recipes (player_id, recipe_id, learned_via) VALUES ($1, $2, $3)",
            player_id,
            "wooden_club",
            "test_seed",
        )
        await pool.execute(
            "INSERT INTO player_inventory (player_id, item_id, data) VALUES ($1, $2, $3::jsonb)",
            player_id,
            "oak_wood",
            json.dumps({"quantity": 2}),
        )

        raw = await _begin_activity_impl(make_context(player_id), "crafting", recipe_id="wooden_club")
        result = json.loads(raw)

        row = await pool.fetchrow("SELECT data FROM async_activities WHERE id = $1", result["activity_id"])
        assert row is not None
        data = json.loads(row["data"])
        assert data["status"] == "in_progress"
        assert data["activity_type"] == "crafting"
        assert data["parameters"]["recipe_id"] == "wooden_club"

        remaining = await pool.fetchval(
            "SELECT (data->>'quantity')::int FROM player_inventory WHERE player_id = $1 AND item_id = $2",
            player_id,
            "oak_wood",
        )
        assert remaining == 1
    finally:
        await pool.execute("DELETE FROM async_activities WHERE player_id = $1", player_id)
        await pool.execute("DELETE FROM player_inventory WHERE player_id = $1", player_id)
        await pool.execute("DELETE FROM player_known_recipes WHERE player_id = $1", player_id)
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)


async def test_begin_activity_workspace_rents_and_debits_gold(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    player_id = "cap_m26_begin_workspace"
    try:
        await seed_player(pool, player_id=player_id)
        await pool.execute(
            "UPDATE players SET data = jsonb_set(data, '{gold}', $2::jsonb) WHERE player_id = $1",
            player_id,
            json.dumps(10),
        )

        raw = await _begin_activity_impl(
            make_context(player_id),
            "workspace",
            workspace_type="workshop",
            npc_id="guildmaster_torin",
            days=1,
        )
        result = json.loads(raw)
        assert result["workspace_type"] == "workshop"

        row = await pool.fetchrow(
            "SELECT workspace_type, location_id FROM workspace_rentals WHERE id = $1", result["rental_id"]
        )
        assert row is not None
        assert row["workspace_type"] == "workshop"
        assert row["location_id"] == "accord_guild_hall"

        gold = await pool.fetchval("SELECT (data->>'gold')::float FROM players WHERE player_id = $1", player_id)
        assert gold == 9.8  # 10 - (2sp workshop / 10sp-per-gold, neutral == 1.0x)
    finally:
        await pool.execute("DELETE FROM workspace_rentals WHERE player_id = $1", player_id)
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)


async def test_begin_activity_experiment_records_a_no_match(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    player_id = "cap_m26_begin_experiment"
    try:
        await seed_player(pool, player_id=player_id)
        await pool.execute(
            "INSERT INTO player_inventory (player_id, item_id, data) VALUES ($1, $2, $3::jsonb)",
            player_id,
            "iron_ingot",
            json.dumps({"quantity": 5}),
        )

        raw = await _begin_activity_impl(
            make_context(player_id),
            "experiment",
            material_ids=["iron_ingot"],
            quantities=[1],
            intended_output="a_nonexistent_item",
        )
        result = json.loads(raw)
        assert result["outcome"] == "no_match"
        assert result["consumed"] is True

        count = await pool.fetchval(
            "SELECT COUNT(*) FROM player_failed_experiments WHERE player_id = $1 AND intended_output = $2",
            player_id,
            "a_nonexistent_item",
        )
        assert count == 1
    finally:
        await pool.execute("DELETE FROM player_failed_experiments WHERE player_id = $1", player_id)
        await pool.execute("DELETE FROM player_inventory WHERE player_id = $1", player_id)
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)


# --- resolve_activity: the two resolve kinds, against real PG ------------------------


async def test_resolve_activity_training_advances_past_the_midpoint(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    player_id = "cap_m26_resolve_training"
    activity_id = "cap_m26_resolve_training_activity"
    try:
        await seed_player(pool, player_id=player_id)
        await seed_training_activity(pool, activity_id=activity_id, player_id=player_id, state="awaiting_decision")

        raw = await _resolve_activity_impl(make_context(player_id), "training", activity_id, decision="aggressive")
        result = json.loads(raw)
        assert result["state"] == "running_second_half"
        assert result["decision_id"] == "aggressive"

        row = await db_training.get_training_activity(activity_id, conn=pool)
        assert row is not None
        assert row["state"] == "running_second_half"
        assert row["data"]["decision_id"] == "aggressive"
    finally:
        await pool.execute("DELETE FROM training_activities WHERE player_id = $1", player_id)
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)


async def test_resolve_activity_companion_errand_resolves_the_outcome(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    player_id = "cap_m26_resolve_errand"
    activity_id = "cap_m26_resolve_errand_activity"
    try:
        await seed_player(pool, player_id=player_id, class_="mage")
        await seed_async_activity(
            pool,
            activity_id=activity_id,
            player_id=player_id,
            errand_type="scout",
            destination="millhaven",
            status="in_progress",
            resolve_at="2026-01-01T00:00:00+00:00",
        )

        raw = await _resolve_activity_impl(make_context(player_id), "companion_errand", activity_id)
        result = json.loads(raw)
        assert "tier" in result

        row = await pool.fetchrow("SELECT data FROM async_activities WHERE id = $1", activity_id)
        assert row is not None
        data = json.loads(row["data"])
        assert data["status"] == "resolved"
        assert data["outcome"] is not None
    finally:
        await pool.execute("DELETE FROM async_activities WHERE player_id = $1", player_id)
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)


# --- query_info: the three folded reads, against real PG -----------------------------


async def test_query_info_training_programs_scopes_choices_to_the_player(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    player_id = f"cap_m26_query_training_{uuid.uuid4().hex}"
    known_spell = "arcane_hold_person"
    try:
        await seed_player(pool, player_id=player_id, class_="mage", known_spells=(known_spell,))
        await pool.execute(
            "UPDATE players SET data = jsonb_set(data, '{level}', '3'::jsonb) WHERE player_id = $1",
            player_id,
        )

        result = json.loads(await _query_info_impl(make_context(player_id), "training_programs"))
        programs = {row["id"]: row for row in result["programs"]}
        choices = programs["arcane_study"]["studiable_spell_ids"]
        assert "arcane_elemental_burst" in choices
        assert known_spell not in choices
        assert "divine_spiritual_weapon" not in choices
        assert "arcane_fireball" not in choices
        assert "studiable_spell_ids" not in programs["combat_basics"]
    finally:
        await pool.execute("DELETE FROM character_spells WHERE player_id = $1", player_id)
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)


async def test_query_info_workspaces_reports_field_as_always_accessible(reset_db_pool: str) -> None:
    raw = await _query_info_impl(make_context(), "workspaces")
    result = json.loads(raw)
    assert "field" in result["accessible"]
    rentable_types = {r["workspace_type"] for r in result["rentable"]}
    assert rentable_types == {"workshop", "forge", "laboratory"}
    assert "forge_laboratory" not in rentable_types


async def test_query_info_recipe_returns_seeded_requirements(reset_db_pool: str) -> None:
    raw = await _query_info_impl(make_context(), "recipe", target_id="wooden_club")
    result = json.loads(raw)
    assert result["recipe_id"] == "wooden_club"
    assert result["workspace_required"] == "field"
