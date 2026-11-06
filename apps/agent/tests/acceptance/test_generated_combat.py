"""Generated catalog combat through exported LiveKit commands and persisted state."""

import json
from random import Random
from unittest.mock import patch
from uuid import uuid4

import pytest
from acceptance.loot_harness import LootHarness
from sample_fixtures import published_payloads

from combat_agent import CombatAgent
from encounter_roles import ROLE_MODIFIERS, derive_role_stats


@pytest.fixture
def mock_combat_agent_factory():
    return None


@pytest.mark.parametrize(
    "levels,companion,tier,difficulty,headcount,dpr,ceiling,window,selected_tier,hud",
    [
        ((3,), "companion_kael", None, "standard", 1.75, 6.83 * 1.75, 3, (3, 5), 1, "moderate"),
        ((3,), "companion_sable", None, "tough", 1.5, 6.83 * 1.5, 4.5, (4, 6), 1, "hard"),
        ((3,), "", None, "standard", 1, 6.83, 3, (3, 5), 1, "moderate"),
        ((3, 7), "companion_kael", None, "boss", 2.75, 6.83 * 1.75 + 9.59, 7, (5, 7), 2, "hard"),
        ((7,), "companion_kael", 1, "standard", 1.75, 9.59 * 1.75, 4, (3, 5), 1, "moderate"),
    ],
)
async def test_generated_entry_resume(
    reset_db_pool, levels, companion, tier, difficulty, headcount, dpr, ceiling, window, selected_tier, hud
):
    h = LootHarness()
    try:
        await h.prepare(levels, companion)
        templates = await h.pool.fetchval("SELECT count(*) FROM encounter_templates")
        with patch("combat_entry.Random", return_value=Random(0)):
            result = await h.command("enter_mode", {"mode": "combat", "difficulty": difficulty, "tier": tier})
        assert isinstance(h.session.current_agent, CombatAgent)
        state = h.sd.combat_state
        assert state is not None
        enemies = [p for p in state.participants if p.type == "enemy"]
        assert enemies and len({p.id for p in state.participants}) == len(state.participants)
        assert {p.id for p in state.participants if p.type == "player"} == set(h.players)
        assert [p.id for p in state.participants if p.type == "companion"] == ([companion] if companion else [])
        assert {p.role for p in enemies} - {"minion"}
        assert sum(p.role == "boss" for p in enemies) <= 1
        assert sum(ROLE_MODIFIERS[p.role].budget_cost for p in enemies) <= ceiling * headcount / 1.75
        assert window[0] <= sum(p.hp_max for p in enemies) / dpr <= window[1]
        rows = {r["id"]: json.loads(r["data"]) for r in await h.pool.fetch("SELECT id,data FROM creatures")}
        assert any(rows[p.creature_id]["tier"] == selected_tier for p in enemies)
        for p in enemies:
            row = rows[p.creature_id]
            assert "greyvale" in row["regions"] and "forest" in row["terrains"]
            assert row["tier"] in (selected_tier, selected_tier - 1)
            assert (row.get("hollow") or {}).get("class") != "named"
            assert p.hp_max == derive_role_stats(row, p.role)["hp"]
            assert p.loot_table_id == row["loot_table_id"] and p.action_pool
            assert p.catalog_narration == row["narration"] and p.catalog_audio == row["audio"]
        assert state.terrain == "forest"
        assert state.spatial is not None
        assert set(state.spatial["positions"]) == {p.id for p in state.participants}
        assert state.spatial["positions"][h.players[0]] == {"x": 0, "y": 0, "z": 0}
        assert state.spatial["locations"] == state.spatial["zones"] == {}
        assert await h.pool.fetchval("SELECT count(*) FROM encounter_templates") == templates
        assert await h.pool.fetchval("SELECT count(*) FROM combat_instances WHERE combat_id=$1", state.combat_id) == 1
        events = published_payloads(h.sd.room)
        assert next(e for e in events if e["type"] == "combat_started")["difficulty"] == hud
        assert any(e["type"] == "combat_ui_update" for e in events)
        before = state.to_dict()
        with (
            patch("encounter_builder.build_encounter", side_effect=AssertionError("resume rebuilt")),
            patch("db_content_queries.get_encounter_template", side_effect=AssertionError("resume template")),
            patch("db_content_queries.load_creature_enemy", side_effect=AssertionError("resume catalog")),
        ):
            assert (await h.reload()).to_dict() == before
            facts = await h.command("query_info", {"kind": "combat"})
            assert facts
        assert result["combat_id"] == state.combat_id
    finally:
        if hasattr(h, "session"):
            await h.close()


@pytest.mark.parametrize(
    "arguments,message",
    [
        ({"encounter_id": "ruins_mawling_pair", "difficulty": "standard"}, "mutually exclusive"),
        ({"encounter_id": "ruins_mawling_pair", "difficulty": "standard", "tier": 1}, "mutually exclusive"),
        ({"encounter_id": "ruins_mawling_pair", "tier": 1}, "mutually exclusive"),
        ({}, "difficulty"),
        ({"tier": 1}, "difficulty"),
        ({"difficulty": "impossible"}, "difficulty"),
        ({"difficulty": "standard", "tier": 0}, "tier must be 1-4"),
        ({"difficulty": "standard", "tier": 5}, "tier must be 1-4"),
        ({"difficulty": "standard", "tier": 4}, "No candidates"),
    ],
)
async def test_refuses_ambiguous_or_invalid_forms(reset_db_pool, arguments, message):
    h = LootHarness()
    try:
        await h.prepare()
        rows = await h.pool.fetchval("SELECT count(*) FROM combat_instances")
        error = await h.command("enter_mode", {"mode": "combat", **arguments}, error=True)
        assert message in error
        assert h.sd.combat_state is None and not isinstance(h.session.current_agent, CombatAgent)
        assert await h.pool.fetchval("SELECT count(*) FROM combat_instances") == rows
        assert not any(e["type"] == "combat_started" for e in published_payloads(h.sd.room))
    finally:
        await h.close()


@pytest.mark.parametrize("terrain,exists", [(None, False), (None, True), ("not_a_terrain", True)])
async def test_unresolvable_terrain_starts_nothing(reset_db_pool, terrain, exists):
    h = LootHarness()
    location_id = f"generated_bad_{uuid4().hex}"
    try:
        await h.prepare(location=location_id)
        if exists:
            row = {"id": location_id, "region": "greyvale", "terrain": terrain}
            await h.pool.execute("INSERT INTO locations (id,data) VALUES ($1,$2::jsonb)", location_id, json.dumps(row))
        rows = await h.pool.fetchval("SELECT count(*) FROM combat_instances")
        error = await h.command("enter_mode", {"mode": "combat", "difficulty": "standard"}, error=True)
        assert location_id in error
        assert ("terrain" if exists else "not found") in error
        assert h.sd.combat_state is None and not isinstance(h.session.current_agent, CombatAgent)
        assert await h.pool.fetchval("SELECT count(*) FROM combat_instances") == rows
        assert not any(e["type"] == "combat_started" for e in published_payloads(h.sd.room))
    finally:
        await h.close()
        await h.pool.execute("DELETE FROM locations WHERE id=$1", location_id)
