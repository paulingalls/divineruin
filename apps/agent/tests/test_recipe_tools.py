"""Tests for the recipe @function_tools (story-006, M5.1).

learn_recipe (mutating: FOR-UPDATE player lock, slot gate, writes
player_known_recipes, ToolError) and query_recipe_requirements (read). Mirror
test_errand_tools.py: make_context + make_db_mod fixtures, injected *_mod seams,
assert conn threading + ToolError shapes.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod

from recipe_tools import _learn_recipe_impl, _query_recipe_requirements_impl

RECIPE = {
    "id": "iron_sword",
    "name": "Iron Sword",
    "category": "weapon",
    "tier": "trained",
    "materials": [{"material_id": "iron_ingot", "quantity": 2, "tier_minimum": 1, "substitutable": True}],
    "optional_materials": [],
    "tainted_materials": False,
    "workspace_required": "forge",
    "crafting_dc": 13,
    "time": "4 hours",
    "async_cycles": 1,
    "output_item": "iron_sword",
    "output_quantity": 1,
    "study_cost": 2,
    "discovery_sources": ["blacksmith_npc"],
    "narration_cues": {"success": "ok", "failure": "no"},
}


def _queries(*, tier="trained", known=2, player=None):
    q = MagicMock()
    q.get_player = AsyncMock(return_value=player if player is not None else {"player_id": "player_1"})
    q.get_single_skill_advancement = AsyncMock(
        return_value={"tier": tier, "use_counter": 0, "narrative_moment_ready": False}
    )
    q.count_player_known_recipes = AsyncMock(return_value=known)
    return q


def _recipes(recipe=RECIPE):
    r = MagicMock()
    r.get_recipe = AsyncMock(return_value=recipe)
    return r


def _mutations(inserted=True):
    m = MagicMock()
    m.add_player_known_recipe = AsyncMock(return_value=inserted)
    return m


class TestLearnRecipe:
    @pytest.mark.asyncio
    async def test_happy_path_locks_player_and_writes(self):
        ctx = make_context()
        db_mod, conn = make_db_mod()
        queries = _queries(tier="trained", known=2)
        mutations = _mutations(inserted=True)
        result = json.loads(
            await _learn_recipe_impl(
                ctx,
                "iron_sword",
                "npc_teaching",
                db_mod=db_mod,
                queries_mod=queries,
                mutations_mod=mutations,
                recipes_mod=_recipes(),
            )
        )
        # Player row locked FOR UPDATE on the txn conn (serializes per-player learns).
        assert queries.get_player.await_args.kwargs.get("for_update") is True
        assert queries.get_player.await_args.kwargs.get("conn") is conn
        # Write threaded through the same conn, with the supplied learned_via.
        add_kwargs = mutations.add_player_known_recipe.await_args
        assert add_kwargs.args[:3] == ("player_1", "iron_sword", "npc_teaching")
        assert add_kwargs.kwargs.get("conn") is conn
        assert result["learned"] == "iron_sword"
        assert result["known_count"] == 3

    @pytest.mark.asyncio
    async def test_disallows_interruptions(self):
        ctx = make_context()
        db_mod, _ = make_db_mod()
        await _learn_recipe_impl(
            ctx,
            "iron_sword",
            "npc_teaching",
            db_mod=db_mod,
            queries_mod=_queries(),
            mutations_mod=_mutations(),
            recipes_mod=_recipes(),
        )
        ctx.disallow_interruptions.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejects_invalid_learned_via(self):
        ctx = make_context()
        db_mod, _ = make_db_mod()
        with pytest.raises(ToolError, match="learned_via"):
            await _learn_recipe_impl(
                ctx,
                "iron_sword",
                "telepathy",
                db_mod=db_mod,
                queries_mod=_queries(),
                mutations_mod=_mutations(),
                recipes_mod=_recipes(),
            )

    @pytest.mark.asyncio
    async def test_unknown_recipe_raises(self):
        ctx = make_context()
        db_mod, _ = make_db_mod()
        with pytest.raises(ToolError, match="recipe"):
            await _learn_recipe_impl(
                ctx,
                "mithril_blade",
                "npc_teaching",
                db_mod=db_mod,
                queries_mod=_queries(),
                mutations_mod=_mutations(),
                recipes_mod=_recipes(recipe=None),
            )

    @pytest.mark.asyncio
    async def test_unknown_player_raises(self):
        ctx = make_context()
        db_mod, _ = make_db_mod()
        with pytest.raises(ToolError, match="player"):
            await _learn_recipe_impl(
                ctx,
                "iron_sword",
                "npc_teaching",
                db_mod=db_mod,
                queries_mod=_queries(player={}),
                mutations_mod=_mutations(),
                recipes_mod=_recipes(),
            )

    @pytest.mark.asyncio
    async def test_over_capacity_raises_and_does_not_write(self):
        ctx = make_context()
        db_mod, _ = make_db_mod()
        mutations = _mutations()
        # trained cap is 8; known=8 -> full.
        with pytest.raises(ToolError, match="slots full"):
            await _learn_recipe_impl(
                ctx,
                "iron_sword",
                "npc_teaching",
                db_mod=db_mod,
                queries_mod=_queries(tier="trained", known=8),
                mutations_mod=mutations,
                recipes_mod=_recipes(),
            )
        mutations.add_player_known_recipe.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_recipe_tier_above_crafting_tier_raises(self):
        ctx = make_context()
        db_mod, _ = make_db_mod()
        # untrained can only learn 'basic'; iron_sword is 'trained'.
        with pytest.raises(ToolError, match="too advanced"):
            await _learn_recipe_impl(
                ctx,
                "iron_sword",
                "npc_teaching",
                db_mod=db_mod,
                queries_mod=_queries(tier="untrained", known=0),
                mutations_mod=_mutations(),
                recipes_mod=_recipes(),
            )

    @pytest.mark.asyncio
    async def test_already_known_raises(self):
        ctx = make_context()
        db_mod, _ = make_db_mod()
        with pytest.raises(ToolError, match="already"):
            await _learn_recipe_impl(
                ctx,
                "iron_sword",
                "npc_teaching",
                db_mod=db_mod,
                queries_mod=_queries(known=2),
                mutations_mod=_mutations(inserted=False),
                recipes_mod=_recipes(),
            )


class TestQueryRecipeRequirements:
    @pytest.mark.asyncio
    async def test_returns_requirement_set(self):
        ctx = make_context()
        result = json.loads(await _query_recipe_requirements_impl(ctx, "iron_sword", recipes_mod=_recipes()))
        assert result["materials"] == RECIPE["materials"]
        assert result["workspace_required"] == "forge"
        assert result["crafting_dc"] == 13
        assert result["time"] == "4 hours"
        assert result["tier"] == "trained"

    @pytest.mark.asyncio
    async def test_unknown_recipe_raises(self):
        ctx = make_context()
        with pytest.raises(ToolError, match="recipe"):
            await _query_recipe_requirements_impl(ctx, "mithril_blade", recipes_mod=_recipes(recipe=None))
