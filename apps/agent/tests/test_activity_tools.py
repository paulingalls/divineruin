"""Tests for activity_tools.begin_activity -- the Phase-5 downtime-activity begin dispatcher
(M26 story-001).

begin_activity(kind) is a pure router: it validates required params per kind then dispatches to
the matching pre-existing ``_impl``. Routing is proven here with injected stub impls (AsyncMock),
not against real DB/content state -- each target ``_impl`` already has its own test suite for its
own behavior.
"""

from unittest.mock import AsyncMock

import pytest
from livekit.agents.llm import ToolError, is_function_tool, is_raw_function_tool
from sample_fixtures import make_context

from activity_tools import _begin_activity_impl, begin_activity


def _mocks():
    training = AsyncMock(return_value="training-result")
    errand_begin = AsyncMock(return_value="errand-begin-result")
    crafting = AsyncMock(return_value="crafting-result")
    workspace = AsyncMock(return_value="workspace-result")
    experiment = AsyncMock(return_value="experiment-result")

    training_mod = _SimpleImpl(_initiate_training_cycle_impl=training)
    errand_mod = _SimpleImpl(_dispatch_companion_errand_impl=errand_begin)
    crafting_mod = _SimpleImpl(_start_crafting_project_impl=crafting, _rent_workspace_impl=workspace)
    experimentation_mod = _SimpleImpl(_experiment_with_materials_impl=experiment)

    mods = {
        "training_mod": training_mod,
        "errand_mod": errand_mod,
        "crafting_mod": crafting_mod,
        "experimentation_mod": experimentation_mod,
    }
    fns = {
        "training": training,
        "errand_begin": errand_begin,
        "crafting": crafting,
        "workspace": workspace,
        "experiment": experiment,
    }
    return mods, fns


class _SimpleImpl:
    """Stands in for a target module, exposing only the named _impl attrs given."""

    def __init__(self, **attrs):
        self._attrs = attrs

    def __getattr__(self, name):
        return self._attrs[name]


async def _begin(kind, **kwargs):
    mods, fns = _mocks()
    ctx = make_context()
    result = await _begin_activity_impl(ctx, kind, **kwargs, **mods)
    return ctx, result, fns


class TestBeginTraining:
    async def test_routes_to_initiate_training_cycle_impl(self):
        ctx, result, fns = await _begin("training", program_id="combat_basics")
        assert result == "training-result"
        fns["training"].assert_awaited_once_with(ctx, "combat_basics")

    async def test_missing_program_id_fails_loud_before_dispatch(self):
        with pytest.raises(ToolError, match="program_id"):
            await _begin("training")


class TestBeginCompanionErrand:
    async def test_routes_to_dispatch_companion_errand_impl(self):
        ctx, result, fns = await _begin(
            "companion_errand", companion_id="companion_kael", errand_type="scout", destination="accord_market_square"
        )
        assert result == "errand-begin-result"
        fns["errand_begin"].assert_awaited_once_with(ctx, "companion_kael", "scout", "accord_market_square")

    async def test_missing_required_param_fails_loud_before_dispatch(self):
        with pytest.raises(ToolError, match="companion_errand"):
            await _begin("companion_errand", companion_id="companion_kael", errand_type="scout")


class TestBeginCrafting:
    async def test_routes_to_start_crafting_project_impl(self):
        ctx, result, fns = await _begin("crafting", recipe_id="iron_dagger_recipe")
        assert result == "crafting-result"
        fns["crafting"].assert_awaited_once_with(ctx, "iron_dagger_recipe")

    async def test_missing_recipe_id_fails_loud_before_dispatch(self):
        with pytest.raises(ToolError, match="recipe_id"):
            await _begin("crafting")


class TestBeginWorkspace:
    async def test_routes_to_rent_workspace_impl(self):
        ctx, result, fns = await _begin("workspace", workspace_type="forge", npc_id="guildmaster_torin", days=3)
        assert result == "workspace-result"
        fns["workspace"].assert_awaited_once_with(ctx, "forge", "guildmaster_torin", 3)

    async def test_missing_days_fails_loud_before_dispatch(self):
        with pytest.raises(ToolError, match="workspace"):
            await _begin("workspace", workspace_type="forge", npc_id="guildmaster_torin")


class TestBeginExperiment:
    async def test_routes_to_experiment_with_materials_impl_with_zipped_materials(self):
        ctx, result, fns = await _begin(
            "experiment",
            material_ids=["iron_ore", "coal"],
            quantities=[2, 1],
            intended_output="iron_ingot",
        )
        assert result == "experiment-result"
        fns["experiment"].assert_awaited_once_with(ctx, {"iron_ore": 2, "coal": 1}, "iron_ingot")

    async def test_missing_intended_output_fails_loud_before_dispatch(self):
        with pytest.raises(ToolError, match="experiment"):
            await _begin("experiment", material_ids=["iron_ore"], quantities=[2])

    async def test_mismatched_lengths_fail_loud_before_dispatch(self):
        with pytest.raises(ToolError, match="same length"):
            await _begin("experiment", material_ids=["iron_ore", "coal"], quantities=[1], intended_output="iron_ingot")

    async def test_duplicate_material_ids_fail_loud_before_dispatch(self):
        with pytest.raises(ToolError, match="duplicates"):
            await _begin(
                "experiment",
                material_ids=["iron_ore", "iron_ore"],
                quantities=[1, 1],
                intended_output="iron_ingot",
            )


class TestBeginUnknownKind:
    async def test_unknown_kind_raises_before_any_dispatch(self):
        mods, fns = _mocks()
        with pytest.raises(ToolError, match="Unknown activity kind"):
            await _begin_activity_impl(make_context(), "not_a_real_kind", **mods)
        for fn in fns.values():
            fn.assert_not_awaited()


class TestToolRegistration:
    def test_begin_activity_is_a_single_strict_function_tool(self):
        assert is_function_tool(begin_activity)
        assert not is_raw_function_tool(begin_activity)
