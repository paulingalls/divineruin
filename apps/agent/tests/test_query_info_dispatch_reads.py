"""Tests for query_info dispatch reads that do not belong to query_tools domains."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents.llm import ToolError
from livekit.agents.voice import RunContext

import abilities
from query_tools import _query_abilities_impl, _query_info_impl
from session_data import SessionData
from system_prompts import COMBAT_SYSTEM_PROMPT, build_system_prompt


@pytest.fixture
def mock_context():
    """Create a mock RunContext with SessionData."""
    context = AsyncMock(spec=RunContext)
    session_data = AsyncMock(spec=SessionData)
    session_data.player_id = "test_player"
    session_data.location_id = "test_location"
    context.userdata = session_data
    return context


class TestQueryInfoRecipeRoute:
    """AC1: query_info(kind='recipe', target_id=<recipe>) routes to _query_recipe_requirements_impl."""

    @pytest.mark.asyncio
    async def test_recipe_routes_to_impl(self, mock_context):
        """Test that kind='recipe' with target_id routes to _query_recipe_requirements_impl."""
        mock_impl_result = json.dumps({"recipe_id": "rec123", "requirements": ["flour", "eggs"]})

        with patch("query_tools.recipe_tools") as mock_recipe_mod:
            mock_recipe_mod._query_recipe_requirements_impl = AsyncMock(return_value=mock_impl_result)

            result = await _query_info_impl(
                mock_context,
                kind="recipe",
                target_id="rec123",
                recipe_mod=mock_recipe_mod,
            )

            assert result == mock_impl_result
            mock_recipe_mod._query_recipe_requirements_impl.assert_called_once_with(mock_context, "rec123")

    @pytest.mark.asyncio
    async def test_recipe_returns_correct_json_shape(self, mock_context):
        """Test that the returned JSON from recipe route has expected shape."""
        recipe_data = {"recipe_id": "rec456", "requirements": ["milk", "cheese"], "time": 120}
        mock_impl_result = json.dumps(recipe_data)

        with patch("query_tools.recipe_tools") as mock_recipe_mod:
            mock_recipe_mod._query_recipe_requirements_impl = AsyncMock(return_value=mock_impl_result)

            result = await _query_info_impl(
                mock_context,
                kind="recipe",
                target_id="rec456",
                recipe_mod=mock_recipe_mod,
            )

            parsed = json.loads(result)
            assert parsed["recipe_id"] == "rec456"
            assert "requirements" in parsed


class TestQueryInfoNoTargetIdKinds:
    """AC2+AC3: training_programs and workspaces work without target_id, unknown kinds fail."""

    @pytest.mark.asyncio
    async def test_training_programs_no_target_id_required(self, mock_context):
        """Test that kind='training_programs' works without target_id (no raise)."""
        mock_impl_result = json.dumps({"programs": ["Apprentice", "Scholar"]})

        with patch("query_tools.training_tools") as mock_training_mod:
            mock_training_mod._query_training_programs_impl = AsyncMock(return_value=mock_impl_result)

            result = await _query_info_impl(
                mock_context,
                kind="training_programs",
                target_id=None,
                training_mod=mock_training_mod,
            )

            assert result == mock_impl_result
            mock_training_mod._query_training_programs_impl.assert_called_once_with(mock_context)

    @pytest.mark.asyncio
    async def test_workspaces_no_target_id_required(self, mock_context):
        """Test that kind='workspaces' works without target_id (no raise)."""
        mock_impl_result = json.dumps({"workspaces": ["smithy", "alchemy_lab"]})

        with patch("query_tools.crafting_tools") as mock_crafting_mod:
            mock_crafting_mod._query_available_workspaces_impl = AsyncMock(return_value=mock_impl_result)

            result = await _query_info_impl(
                mock_context,
                kind="workspaces",
                target_id=None,
                crafting_mod=mock_crafting_mod,
            )

            assert result == mock_impl_result
            mock_crafting_mod._query_available_workspaces_impl.assert_called_once_with(mock_context)

    @pytest.mark.asyncio
    async def test_abilities_no_target_id_required(self, mock_context):
        with patch(
            "query_tools._query_abilities_impl", new_callable=AsyncMock, return_value='{"abilities":[]}'
        ) as read:
            result = await _query_info_impl(mock_context, kind="abilities")

        assert result == '{"abilities":[]}'
        read.assert_awaited_once_with(mock_context)

    @pytest.mark.asyncio
    async def test_unknown_kind_fails_loud(self, mock_context):
        """Test that unknown kind still raises ToolError."""
        with pytest.raises(ToolError, match="Unknown query_info kind"):
            await _query_info_impl(
                mock_context,
                kind="unknown_kind",
                target_id="some_id",
            )

    @pytest.mark.asyncio
    async def test_recipe_without_target_id_still_requires_it(self, mock_context):
        """Test that kind='recipe' without target_id raises error (recipe needs target_id)."""
        with pytest.raises(ToolError, match="requires target_id"):
            await _query_info_impl(
                mock_context,
                kind="recipe",
                target_id=None,
            )


class TestQueryAbilities:
    def _dependencies(self, *, player=None, known=None, active_variant=None):
        queries = MagicMock()
        queries.get_player = AsyncMock(return_value=player)
        persistence = MagicMock()
        persistence.get_character_abilities = AsyncMock(return_value=known or [])
        persistence.get_active_variant = AsyncMock(return_value=active_variant)
        return queries, persistence

    @pytest.mark.asyncio
    async def test_surfaces_class_catalog_owned_elective_and_active_variant(self, mock_context):
        queries, persistence = self._dependencies(
            player={"class": "warrior"},
            known=[{"ability_id": "warrior_cleaving_blow", "equipped": True}],
            active_variant="warrior_cleaving_blow_drathian",
        )

        payload = json.loads(await _query_abilities_impl(mock_context, queries=queries, persistence=persistence))
        rows = {row["id"]: row for row in payload["abilities"]}
        catalog = abilities.get_archetype_abilities("warrior")
        expected_ids = {
            ability.id
            for ability in catalog
            if ability.ability_type in ("core", "reaction") or ability.id == "warrior_cleaving_blow"
        }

        assert set(rows) == expected_ids
        assert all(rows[ability.id]["name"] == ability.name for ability in catalog if ability.id in rows)
        reactions = [ability for ability in catalog if ability.ability_type == "reaction"]
        assert reactions
        assert all(rows[ability.id]["window"] == ability.window for ability in reactions)
        assert rows["warrior_cleaving_blow"]["active_variant_id"] == "warrior_cleaving_blow_drathian"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("player", [None, {}, {"class": None}])
    async def test_missing_player_or_class_fails_loud(self, mock_context, player):
        queries, persistence = self._dependencies(player=player)

        with pytest.raises(ToolError, match="class"):
            await _query_abilities_impl(mock_context, queries=queries, persistence=persistence)

    @pytest.mark.asyncio
    async def test_class_with_no_catalog_abilities_fails_loud(self, mock_context):
        # An empty payload would read to the DM as "you own no reactions" — a wrong answer that
        # sounds like an answer, which is what this kind exists to remove.
        queries, persistence = self._dependencies(player={"class": "not_an_archetype"})

        with pytest.raises(ToolError, match="not_an_archetype"):
            await _query_abilities_impl(mock_context, queries=queries, persistence=persistence)

    @pytest.mark.asyncio
    async def test_unknown_persisted_elective_is_a_tool_error(self, mock_context):
        queries, persistence = self._dependencies(
            player={"class": "warrior"},
            known=[{"ability_id": "missing_catalog_ability", "equipped": True}],
        )

        with pytest.raises(ToolError, match="missing_catalog_ability"):
            await _query_abilities_impl(mock_context, queries=queries, persistence=persistence)


def test_prompts_name_ability_id_producer():
    exploration = build_system_prompt("accord_guild_hall")
    for prompt in (exploration, COMBAT_SYSTEM_PROMPT):
        assert 'query_info(kind="abilities")' in prompt
        assert "window" in prompt
        assert "variant" in prompt

    # Surfacing the variant id is only half of constraint 6: the tool that consumes it has to
    # say so, or the DM holds an id it has no documented route for.
    activate_bullet = next(line for line in exploration.split("- ") if line.startswith("activate:"))
    assert "active_variant_id" in activate_bullet


class TestQueryInfoE2E:
    """AC4: E2E tests against real database and _impl functions."""

    @pytest.mark.asyncio
    async def test_recipe_route_returns_valid_json(self, mock_context, dev_db_pool):
        """AC4: query_info(kind='recipe') returns JSON with expected recipe fields."""
        import recipes

        # Get first recipe from seeded data
        recipe_list = await recipes.list_recipes()
        if not recipe_list:
            pytest.skip("No recipes in test DB")

        recipe_id = recipe_list[0]["id"]

        # Call query_info with real _impl (no mocks)
        result = await _query_info_impl(mock_context, kind="recipe", target_id=recipe_id)

        # Verify JSON shape and contents
        parsed = json.loads(result)
        assert parsed["recipe_id"] == recipe_id
        assert "name" in parsed
        assert "tier" in parsed
        assert "materials" in parsed
        assert "time" in parsed

    @pytest.mark.asyncio
    async def test_training_programs_route_returns_valid_json(self, mock_context, dev_db_pool):
        """AC4: query_info(kind='training_programs') returns JSON with programs list."""
        # Call query_info with real _impl (no mocks)
        result = await _query_info_impl(mock_context, kind="training_programs")

        # Verify JSON shape
        parsed = json.loads(result)
        assert "programs" in parsed
        assert isinstance(parsed["programs"], list)

    @pytest.mark.asyncio
    async def test_workspaces_route_returns_valid_json(self, mock_context, dev_db_pool):
        """AC4: query_info(kind='workspaces') returns JSON with workspace data."""
        # Call query_info with real _impl (no mocks)
        result = await _query_info_impl(mock_context, kind="workspaces")

        # Verify JSON shape
        parsed = json.loads(result)
        assert "accessible" in parsed
        assert "rentable" in parsed
        assert isinstance(parsed["accessible"], list)
        assert isinstance(parsed["rentable"], list)
