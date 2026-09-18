import json
import uuid
from typing import get_args
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents.llm import ToolError
from livekit.agents.voice import RunContext
from sample_fixtures import make_context, make_db_mod

import abilities
import spells
from query_tools import _query_abilities_impl, _query_info_impl
from session_data import SessionData
from system_prompts import COMBAT_SYSTEM_PROMPT, DISPATCH_MODE_PROMPT, build_system_prompt
from training_tools import _initiate_training_cycle_impl, _query_training_programs_impl

SPELL_STANDARD_PROGRAM = {
    "id": "arcane_study",
    "name": "Arcane Study",
    "training_activity_type": "spell_standard",
}
SPELL_MAJOR_PROGRAM = {
    "id": "major_study",
    "name": "Major Study",
    "training_activity_type": "spell_major",
}
ORDINARY_PROGRAM = {
    "id": "combat_basics",
    "name": "Combat Fundamentals",
    "training_activity_type": "technique_base",
}


@pytest.fixture
def mock_context():
    context = AsyncMock(spec=RunContext)
    session_data = AsyncMock(spec=SessionData)
    session_data.player_id = "test_player"
    session_data.location_id = "test_location"
    context.userdata = session_data
    return context


class TestQueryInfoRecipeRoute:
    @pytest.mark.asyncio
    async def test_recipe_routes_to_impl(self, mock_context):
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
            mock_crafting_mod._query_available_workspaces_impl.assert_called_once_with(mock_context, None)

    @pytest.mark.asyncio
    async def test_workspaces_forwards_npc_target(self, mock_context):
        mock_crafting_mod = MagicMock()
        mock_crafting_mod._query_available_workspaces_impl = AsyncMock(return_value='{"rentable": []}')

        result = await _query_info_impl(
            mock_context,
            kind="workspaces",
            target_id="grimjaw",
            crafting_mod=mock_crafting_mod,
        )

        assert result == '{"rentable": []}'
        mock_crafting_mod._query_available_workspaces_impl.assert_awaited_once_with(mock_context, "grimjaw")

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


class TestQueryTrainingPrograms:
    def _dependencies(self, *, player=None, known=None):
        programs = [SPELL_STANDARD_PROGRAM, SPELL_MAJOR_PROGRAM, ORDINARY_PROGRAM]
        content = MagicMock()
        content.list_training_programs = AsyncMock(return_value=programs)
        content.get_training_program = AsyncMock(
            side_effect=lambda program_id: next(row for row in programs if row["id"] == program_id)
        )
        queries = MagicMock(get_player=AsyncMock(return_value=player))
        library = MagicMock(
            get_known=AsyncMock(return_value=known or []),
            list_learning_progress=AsyncMock(return_value=[]),
        )
        return content, queries, library

    @pytest.mark.asyncio
    async def test_spell_choices_equal_ids_the_start_wall_accepts(self):
        player = {"class": "mage", "level": 3}
        known = [{"spell_id": "arcane_hold_person"}]
        content, queries, library = self._dependencies(player=player, known=known)
        context = make_context()

        with (
            patch("training_tools.db_queries.get_player", queries.get_player),
            patch("training_tools.character_spells.get_known", library.get_known),
            patch("training_tools.character_spells.list_learning_progress", library.list_learning_progress),
        ):
            result = json.loads(await _query_training_programs_impl(context, db_content_mod=content))
            rows = {row["id"]: row for row in result["programs"]}

            for program in (SPELL_STANDARD_PROGRAM, SPELL_MAJOR_PROGRAM):
                accepted = set()
                for source in get_args(spells.SpellSource):
                    for spell in spells.get_spells_by_source(source):
                        training = MagicMock()
                        training.get_player_training_activities = AsyncMock(return_value=[])
                        training.create_training_activity = AsyncMock(return_value="training_id")
                        db_mod, _ = make_db_mod()
                        try:
                            await _initiate_training_cycle_impl(
                                context,
                                program["id"],
                                spell_id=spell.id,
                                db_mod=db_mod,
                                db_training_mod=training,
                                db_content_mod=content,
                            )
                        except ToolError:
                            pass
                        if training.create_training_activity.await_count:
                            accepted.add(spell.id)

                assert rows[program["id"]]["studiable_spell_ids"] == sorted(accepted)

        assert "arcane_hold_person" not in rows["arcane_study"]["studiable_spell_ids"]
        assert rows["major_study"]["studiable_spell_ids"] == []
        assert "studiable_spell_ids" not in rows["combat_basics"]
        content.list_training_programs.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "player",
        [{}, {"class": "warrior", "level": 5}],
        ids=["onboarding", "martial"],
    )
    async def test_non_caster_gets_every_program_with_empty_spell_choices(self, player):
        """Two orderings are load-bearing here. The onboarding row (auth.ts writes data={} at
        first login) has no archetype, so the chassis lookup must stay INSIDE the spell branch
        or the whole listing dies on a ToolError; and leveling.is_spell_tier_unlocked raises a
        bare ValueError on a non-caster, so the source check must refuse a martial first."""
        content, queries, library = self._dependencies(player=player)

        with (
            patch("training_tools.db_queries.get_player", queries.get_player),
            patch("training_tools.character_spells.get_known", library.get_known),
            patch("training_tools.character_spells.list_learning_progress", library.list_learning_progress),
        ):
            result = json.loads(await _query_training_programs_impl(make_context(), db_content_mod=content))

        rows = {row["id"]: row for row in result["programs"]}
        assert set(rows) == {SPELL_STANDARD_PROGRAM["id"], SPELL_MAJOR_PROGRAM["id"], ORDINARY_PROGRAM["id"]}
        assert rows[ORDINARY_PROGRAM["id"]] == ORDINARY_PROGRAM
        for program in (SPELL_STANDARD_PROGRAM, SPELL_MAJOR_PROGRAM):
            assert rows[program["id"]] == {**program, "studiable_spell_ids": []}

    @pytest.mark.asyncio
    async def test_returns_persisted_spell_learning_progress(self):
        content, queries, library = self._dependencies(player={"class": "mage", "level": 3})
        library.list_learning_progress.return_value = [
            {
                "spell_id": "arcane_hold_person",
                "cycles_completed": 1,
                "cycles_required": 3,
            }
        ]

        result = json.loads(
            await _query_training_programs_impl(
                make_context(),
                db_content_mod=content,
                queries_mod=queries,
                character_spells_mod=library,
            )
        )

        assert result["spell_learning_progress"] == library.list_learning_progress.return_value
        library.list_learning_progress.assert_awaited_once_with("player_1")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("player", "message"),
        [(None, "Unknown player"), ({"class": "not_an_archetype", "level": 3}, "Unknown archetype")],
    )
    async def test_missing_player_or_unknown_class_fails_loud(self, player, message):
        content, queries, library = self._dependencies(player=player)
        with (
            patch("training_tools.db_queries.get_player", queries.get_player),
            patch("training_tools.character_spells.get_known", library.get_known),
            patch("training_tools.character_spells.list_learning_progress", library.list_learning_progress),
            pytest.raises(ToolError, match=message),
        ):
            await _query_training_programs_impl(make_context(), db_content_mod=content)


def test_training_prompt_names_spell_id_producer():
    training = DISPATCH_MODE_PROMPT[
        DISPATCH_MODE_PROMPT.index("For training:") : DISPATCH_MODE_PROMPT.index("For companion errands:")
    ]
    assert "spell_id" in training
    assert "studiable_spell_ids" in training
    assert "from that row" in training
    assert "spell_learning_progress" in training
    # A non-caster and an onboarding player get the spell row back with an EMPTY list rather
    # than a refusal (AC5), so the prompt has to say what an empty list means — otherwise the
    # DM offers Arcane Study to a warrior and begin_activity refuses (constraint 6).
    assert "empty studiable_spell_ids" in training


class TestQueryAbilities:
    def _dependencies(self, *, player=None, known=None, active_variant=None):
        queries = MagicMock()
        queries.get_player = AsyncMock(return_value=player)
        persistence = MagicMock()
        persistence.get_character_abilities = AsyncMock(return_value=known or [])
        persistence.get_active_variant = AsyncMock(return_value=active_variant)
        library = MagicMock()
        library.get_known = AsyncMock(return_value=[])
        return queries, persistence, library

    async def _read(self, context, dependencies):
        queries, persistence, library = dependencies
        return await _query_abilities_impl(
            context, queries=queries, persistence=persistence, character_spells_mod=library
        )

    @pytest.mark.asyncio
    async def test_surfaces_class_catalog_owned_elective_and_active_variant(self, mock_context):
        queries, persistence, library = self._dependencies(
            player={"class": "warrior", "level": 8},
            known=[{"ability_id": "warrior_cleaving_blow", "equipped": True}],
            active_variant="warrior_cleaving_blow_drathian",
        )

        payload = json.loads(await self._read(mock_context, (queries, persistence, library)))
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
        assert rows["warrior_devastating_strike"]["combat"] is False

    @pytest.mark.asyncio
    async def test_spell_backed_row_names_its_combat_spell_id(self, mock_context):
        dependencies = self._dependencies(player={"class": "cleric", "level": 1})

        payload = json.loads(await self._read(mock_context, dependencies))
        rows = {row["id"]: row for row in payload["abilities"]}

        assert rows["cleric_heal_wounds"]["spell_id"] == "divine_heal_wounds"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("player", [None, {}, {"class": None}])
    async def test_missing_player_or_class_fails_loud(self, mock_context, player):
        queries, persistence, _library = self._dependencies(player=player)

        with pytest.raises(ToolError, match="class"):
            await _query_abilities_impl(mock_context, queries=queries, persistence=persistence)

    @pytest.mark.asyncio
    async def test_class_with_no_catalog_abilities_fails_loud(self, mock_context):
        # An empty payload would read to the DM as "you own no reactions" — a wrong answer that
        # sounds like an answer, which is what this kind exists to remove.
        queries, persistence, library = self._dependencies(player={"class": "not_an_archetype", "level": 1})

        with pytest.raises(ToolError, match="not_an_archetype"):
            await self._read(mock_context, (queries, persistence, library))

    @pytest.mark.asyncio
    async def test_unknown_persisted_elective_is_a_tool_error(self, mock_context):
        queries, persistence, library = self._dependencies(
            player={"class": "warrior", "level": 8},
            known=[{"ability_id": "missing_catalog_ability", "equipped": True}],
        )

        with pytest.raises(ToolError, match="missing_catalog_ability"):
            await self._read(mock_context, (queries, persistence, library))

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("level", "expected"),
        [
            (1, {"bard_inspire"}),
            (9, {"bard_inspire", "bard_mass_inspire"}),
        ],
    )
    async def test_filters_catalog_abilities_by_player_level(self, mock_context, level, expected):
        queries, persistence, library = self._dependencies(player={"class": "bard", "level": level})

        payload = json.loads(await self._read(mock_context, (queries, persistence, library)))
        rows = {row["id"]: row for row in payload["abilities"]}
        ids = set(rows)

        assert expected <= ids
        assert ("bard_mass_inspire" in ids) is (level >= 9)
        assert "combat" not in rows["bard_inspire"]


def test_prompts_name_ability_id_producer():
    exploration = build_system_prompt("accord_guild_hall")
    for prompt in (exploration, COMBAT_SYSTEM_PROMPT):
        assert 'query_info(kind="abilities")' in prompt
        assert "window" in prompt
        assert "spell id" in prompt.lower()

    # Surfacing the variant id is only half of constraint 6: the tool that consumes it has to
    # say so, or the DM holds an id it has no documented route for.
    assert "variant" in exploration
    activate_bullet = next(line for line in exploration.split("- ") if line.startswith("activate:"))
    assert "active_variant_id" in activate_bullet

    assert "variant" in COMBAT_SYSTEM_PROMPT.lower()
    assert "active_variant_id" in COMBAT_SYSTEM_PROMPT
    assert "spell_id" in COMBAT_SYSTEM_PROMPT
    assert "combat: false" in COMBAT_SYSTEM_PROMPT


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
        player_id = f"query_training_{uuid.uuid4().hex}"
        mock_context.userdata.player_id = player_id
        await dev_db_pool.execute(
            "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb)",
            player_id,
            json.dumps({"player_id": player_id, "name": "Mira", "class": "mage", "level": 3}),
        )
        try:
            parsed = json.loads(await _query_info_impl(mock_context, kind="training_programs"))
            assert isinstance(parsed["programs"], list)
            arcane_study = next(row for row in parsed["programs"] if row["id"] == "arcane_study")
            assert arcane_study["studiable_spell_ids"]
        finally:
            await dev_db_pool.execute("DELETE FROM players WHERE player_id = $1", player_id)

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
