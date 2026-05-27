"""Tests for the experimentation system (story-004, M5.3).

Pure core (resolve_experimentation, find_matching_recipe, make_combination_key) plus
the experiment_with_materials tool. The tool resolves immediately (decision
experimentation-immediate): roll d20+crafting-mod vs base_dc+4, consume materials, and
either teach the matched recipe (success) or record a no-match combo. player_failed_experiments
records/short-circuits ONLY no-match combos (decision experimentation-dedup-no-match-only);
a roll-failure on a real recipe is retryable.
"""

import json
import random
from unittest.mock import AsyncMock, MagicMock

import pytest
from dice_seeds import seed_for_d20 as _seed_for_d20
from sample_fixtures import make_context, make_db_mod

import experimentation
import experimentation_db
from experimentation_tools import _experiment_with_materials_impl

# SAMPLE_PLAYER's arcana modifier is +3 (level 3, proficient). With base_dc=13 the
# experimentation DC is base_dc+4 = 17, so total = d20+3 succeeds when d20 >= 14.
SAMPLE_PLAYER = {
    "level": 3,
    "attributes": {"intelligence": 10},
    "proficiencies": ["arcana"],
}

CATALOG = {
    "iron_ingot": {"category": "metal", "tier": 1},
    "leather_strip": {"category": "leather", "tier": 1},
    "oak_plank": {"category": "wood", "tier": 1},
}

IRON_SWORD = {
    "id": "iron_sword",
    "output_item": "iron_sword",
    "crafting_dc": 13,
    "materials": [
        {"material_id": "iron_ingot", "quantity": 2, "tier_minimum": 1, "substitutable": False},
        {"material_id": "leather_strip", "quantity": 1, "tier_minimum": 1, "substitutable": False},
    ],
}
OAK_SHIELD = {
    "id": "oak_shield",
    "output_item": "oak_shield",
    "crafting_dc": 11,
    "materials": [{"material_id": "oak_plank", "quantity": 3, "tier_minimum": 1, "substitutable": False}],
}
RECIPES = [IRON_SWORD, OAK_SHIELD]


class TestResolveExperimentation:
    def test_dc_is_base_plus_four(self):
        out = experimentation.resolve_experimentation(SAMPLE_PLAYER, 13, rng=random.Random(_seed_for_d20(10)))
        assert out.dc == 17

    def test_success_when_total_meets_dc(self):
        # d20=14 + mod 3 = 17 == dc 17 -> success (margin 0).
        out = experimentation.resolve_experimentation(SAMPLE_PLAYER, 13, rng=random.Random(_seed_for_d20(14)))
        assert out.success is True
        assert out.roll == 14
        assert out.total == 17
        assert out.margin == 0

    def test_failure_when_below_dc(self):
        out = experimentation.resolve_experimentation(SAMPLE_PLAYER, 13, rng=random.Random(_seed_for_d20(13)))
        assert out.success is False
        assert out.margin < 0

    def test_deterministic_by_seed(self):
        a = experimentation.resolve_experimentation(SAMPLE_PLAYER, 13, rng=random.Random(5))
        b = experimentation.resolve_experimentation(SAMPLE_PLAYER, 13, rng=random.Random(5))
        assert a == b


class TestFindMatchingRecipe:
    def test_matches_on_output_and_materials(self):
        provided = {"iron_ingot": 2, "leather_strip": 1}
        match = experimentation.find_matching_recipe(RECIPES, "iron_sword", provided, CATALOG)
        assert match is IRON_SWORD

    def test_no_match_on_wrong_output(self):
        provided = {"iron_ingot": 2, "leather_strip": 1}
        assert experimentation.find_matching_recipe(RECIPES, "mithril_blade", provided, CATALOG) is None

    def test_no_match_when_materials_insufficient(self):
        provided = {"iron_ingot": 1}  # need 2 + a leather_strip
        assert experimentation.find_matching_recipe(RECIPES, "iron_sword", provided, CATALOG) is None

    def test_exclude_ids_skips_listed_recipes(self):
        provided = {"iron_ingot": 2, "leather_strip": 1}
        excluded = frozenset({"iron_sword"})
        assert (
            experimentation.find_matching_recipe(RECIPES, "iron_sword", provided, CATALOG, exclude_ids=excluded) is None
        )

    def test_exclude_ids_reaches_later_unknown_same_output(self):
        # A second recipe makes the same output from the same materials; excluding the first
        # must surface the second rather than returning None.
        alt_sword = {**IRON_SWORD, "id": "iron_sword_alt"}
        recipes = [IRON_SWORD, alt_sword]
        provided = {"iron_ingot": 2, "leather_strip": 1}
        match = experimentation.find_matching_recipe(
            recipes, "iron_sword", provided, CATALOG, exclude_ids=frozenset({"iron_sword"})
        )
        assert match is alt_sword


class TestMakeCombinationKey:
    def test_canonical_order_independent(self):
        a = experimentation.make_combination_key({"iron_ingot": 2, "leather_strip": 1})
        b = experimentation.make_combination_key({"leather_strip": 1, "iron_ingot": 2})
        assert a == b

    def test_distinct_combos_differ(self):
        a = experimentation.make_combination_key({"iron_ingot": 2})
        b = experimentation.make_combination_key({"iron_ingot": 3})
        assert a != b


class TestExperimentationDb:
    @pytest.mark.asyncio
    async def test_record_failed_experiment_inserts(self):
        conn = AsyncMock()
        await experimentation_db.record_failed_experiment("player_1", "mithril_blade", "iron:5", conn=conn)
        conn.execute.assert_awaited_once()
        args = conn.execute.call_args[0]
        assert args[1:] == ("player_1", "mithril_blade", "iron:5")

    @pytest.mark.asyncio
    async def test_has_failed_experiment_true_when_row_exists(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        assert await experimentation_db.has_failed_experiment("player_1", "mithril_blade", "iron:5", conn=conn) is True

    @pytest.mark.asyncio
    async def test_has_failed_experiment_false_when_absent(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)
        assert await experimentation_db.has_failed_experiment("player_1", "x", "y", conn=conn) is False


def _seams(*, recipes_list, known_ids, available, alloc_satisfied=True):
    """Assemble the mocked *_mod seams for the experiment tool. Returns (kwargs, conn, mods)."""
    db_mod, conn = make_db_mod()
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value={"player_id": "player_1", **SAMPLE_PLAYER})
    queries.get_player_materials = AsyncMock(return_value=available)
    queries.get_player_known_recipe_ids = AsyncMock(return_value=list(known_ids))
    mutations = MagicMock()
    mutations.consume_player_materials = AsyncMock()
    mutations.add_player_known_recipe = AsyncMock(return_value=True)
    recipes_mod = MagicMock()
    recipes_mod.list_recipes = AsyncMock(return_value=recipes_list)
    materials_mod = MagicMock()
    materials_mod.get_materials_catalog = AsyncMock(return_value=CATALOG)
    validation = MagicMock()
    validation.allocate_materials = MagicMock(
        return_value=MagicMock(satisfied=alloc_satisfied, by_id=available, flat=[], reason="insufficient")
    )
    exp_db = MagicMock()
    exp_db.has_failed_experiment = AsyncMock(return_value=False)
    exp_db.record_failed_experiment = AsyncMock()
    mods = {
        "queries": queries,
        "mutations": mutations,
        "exp_db": exp_db,
        "validation": validation,
    }
    kwargs = dict(
        db_mod=db_mod,
        queries_mod=queries,
        mutations_mod=mutations,
        recipes_mod=recipes_mod,
        materials_mod=materials_mod,
        validation_mod=validation,
        exp_db_mod=exp_db,
    )
    return kwargs, conn, mods


class TestExperimentWithMaterials:
    @pytest.mark.asyncio
    async def test_success_learns_recipe(self):
        kwargs, _, mods = _seams(
            recipes_list=[IRON_SWORD], known_ids=[], available={"iron_ingot": 2, "leather_strip": 1}
        )
        out = json.loads(
            await _experiment_with_materials_impl(
                make_context(),
                {"iron_ingot": 2, "leather_strip": 1},
                "iron_sword",
                rng=random.Random(_seed_for_d20(20)),
                **kwargs,
            )
        )
        assert out["outcome"] == "success"
        assert out["learned_recipe"] == "iron_sword"
        assert out["produced_item"] == "iron_sword"
        mods["mutations"].add_player_known_recipe.assert_awaited_once()
        assert mods["mutations"].add_player_known_recipe.call_args[0][2] == "experimentation"
        mods["mutations"].consume_player_materials.assert_awaited_once()
        mods["exp_db"].record_failed_experiment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_roll_failure_is_retryable_not_recorded(self):
        kwargs, _, mods = _seams(
            recipes_list=[IRON_SWORD], known_ids=[], available={"iron_ingot": 2, "leather_strip": 1}
        )
        out = json.loads(
            await _experiment_with_materials_impl(
                make_context(),
                {"iron_ingot": 2, "leather_strip": 1},
                "iron_sword",
                rng=random.Random(_seed_for_d20(1)),
                **kwargs,
            )
        )
        assert out["outcome"] == "failure"
        assert out["learned_recipe"] is None
        assert out["retryable"] is True
        mods["mutations"].consume_player_materials.assert_awaited_once()  # spent on a real attempt
        mods["exp_db"].record_failed_experiment.assert_not_awaited()  # retryable, not recorded
        mods["mutations"].add_player_known_recipe.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_match_consumes_and_records(self):
        kwargs, _, mods = _seams(recipes_list=[IRON_SWORD], known_ids=[], available={"scrap": 3})
        out = json.loads(
            await _experiment_with_materials_impl(
                make_context(),
                {"scrap": 3},
                "mithril_blade",
                **kwargs,
            )
        )
        assert out["outcome"] == "no_match"
        assert out["consumed"] is True
        mods["mutations"].consume_player_materials.assert_awaited_once()
        mods["exp_db"].record_failed_experiment.assert_awaited_once()
        mods["mutations"].add_player_known_recipe.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_duplicate_no_match_short_circuits_without_consuming(self):
        kwargs, _, mods = _seams(recipes_list=[IRON_SWORD], known_ids=[], available={"scrap": 3})
        mods["exp_db"].has_failed_experiment = AsyncMock(return_value=True)
        kwargs["exp_db_mod"].has_failed_experiment = mods["exp_db"].has_failed_experiment
        out = json.loads(
            await _experiment_with_materials_impl(
                make_context(),
                {"scrap": 3},
                "mithril_blade",
                **kwargs,
            )
        )
        assert out["outcome"] == "already_tried"
        assert out["consumed"] is False
        mods["mutations"].consume_player_materials.assert_not_awaited()
        mods["exp_db"].record_failed_experiment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_already_known_recipe_raises(self):
        from livekit.agents.llm import ToolError

        kwargs, _, _ = _seams(
            recipes_list=[IRON_SWORD], known_ids=["iron_sword"], available={"iron_ingot": 2, "leather_strip": 1}
        )
        with pytest.raises(ToolError, match="already know"):
            await _experiment_with_materials_impl(
                make_context(), {"iron_ingot": 2, "leather_strip": 1}, "iron_sword", **kwargs
            )

    @pytest.mark.asyncio
    async def test_unknown_match_reached_despite_earlier_known_same_output(self):
        # IRON_SWORD (known, first in list) and an alt recipe (unknown) both make iron_sword
        # from the same materials. The player should discover the UNKNOWN alt, not be told
        # "you already know it".
        alt_sword = {**IRON_SWORD, "id": "iron_sword_alt"}
        kwargs, _, mods = _seams(
            recipes_list=[IRON_SWORD, alt_sword],
            known_ids=["iron_sword"],
            available={"iron_ingot": 2, "leather_strip": 1},
        )
        out = json.loads(
            await _experiment_with_materials_impl(
                make_context(),
                {"iron_ingot": 2, "leather_strip": 1},
                "iron_sword",
                rng=random.Random(_seed_for_d20(20)),
                **kwargs,
            )
        )
        assert out["outcome"] == "success"
        assert out["learned_recipe"] == "iron_sword_alt"
        assert mods["mutations"].add_player_known_recipe.call_args[0][1] == "iron_sword_alt"

    @pytest.mark.asyncio
    async def test_only_known_same_output_treated_as_already_known(self):
        from livekit.agents.llm import ToolError

        # The single recipe making iron_sword is already known -> no unknown match exists,
        # so the tool raises "already know" rather than reaching the no-match path.
        kwargs, _, mods = _seams(
            recipes_list=[IRON_SWORD], known_ids=["iron_sword"], available={"iron_ingot": 2, "leather_strip": 1}
        )
        with pytest.raises(ToolError, match="already know"):
            await _experiment_with_materials_impl(
                make_context(), {"iron_ingot": 2, "leather_strip": 1}, "iron_sword", **kwargs
            )
        mods["mutations"].consume_player_materials.assert_not_awaited()
        mods["exp_db"].record_failed_experiment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_known_recipe_undersupplied_is_already_known_not_no_match(self):
        from livekit.agents.llm import ToolError

        # Player KNOWS iron_sword but offers too few materials. This must NOT burn materials
        # or record a bogus no-match for a recipe they own — it's "craft it with the right
        # materials" (satisfaction-independent already-known check).
        kwargs, _, mods = _seams(recipes_list=[IRON_SWORD], known_ids=["iron_sword"], available={"iron_ingot": 1})
        with pytest.raises(ToolError, match="already know"):
            await _experiment_with_materials_impl(make_context(), {"iron_ingot": 1}, "iron_sword", **kwargs)
        mods["mutations"].consume_player_materials.assert_not_awaited()
        mods["exp_db"].record_failed_experiment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_invalid_material_id_raises(self):
        from livekit.agents.llm import ToolError

        kwargs, _, mods = _seams(recipes_list=[IRON_SWORD], known_ids=[], available={"iron_ingot": 2})
        with pytest.raises(ToolError):
            await _experiment_with_materials_impl(make_context(), {"bad id!": 1}, "iron_sword", **kwargs)
        mods["mutations"].consume_player_materials.assert_not_awaited()


class TestStrictSchema:
    def test_no_open_ended_map_in_strict_schema(self):
        # Anthropic strict tools reject a typed open-ended map (additionalProperties: {..}).
        # The public tool must expose scalar arrays, so the only additionalProperties in the
        # built strict schema are `false` (closed objects), never a dict. (ADR 0004.)
        from livekit.agents.llm.utils import build_strict_openai_schema

        from experimentation_tools import experiment_with_materials

        schema = build_strict_openai_schema(experiment_with_materials)

        def assert_no_dict_additional_props(node):
            if isinstance(node, dict):
                if "additionalProperties" in node:
                    assert node["additionalProperties"] is False
                for value in node.values():
                    assert_no_dict_additional_props(value)
            elif isinstance(node, list):
                for item in node:
                    assert_no_dict_additional_props(item)

        assert_no_dict_additional_props(schema)


class TestDispatchToolsCap:
    def test_experiment_tool_registered_under_cap(self):
        import dispatch_agent
        from experimentation_tools import experiment_with_materials
        from llm_config import MAX_STRICT_TOOLS

        assert experiment_with_materials in dispatch_agent.DISPATCH_TOOLS
        assert len(dispatch_agent.DISPATCH_TOOLS) <= MAX_STRICT_TOOLS
