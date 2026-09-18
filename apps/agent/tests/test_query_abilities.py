import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from archetype_abilities_config_fixture import load_fixture_config
from livekit.agents.llm import ToolError
from livekit.agents.voice import RunContext

import abilities
import combat_ability
import spells
from combat_phase import advance_combat_phase
from query_tools import _query_abilities_impl
from session_data import CombatParticipant, CombatState, SessionData


def _solo_player_state() -> CombatState:
    """A one-player combat at the declaration beat — enough for the declare gate, which validates an
    ABILITY action without reading targets. advance_combat_phase is pure, so one state serves the
    whole walk."""
    return CombatState(
        combat_id="query-declarability",
        participants=[
            CombatParticipant(
                id="test_player",
                name="Test Player",
                type="player",
                initiative=10,
                hp_current=10,
                hp_max=10,
                ac=10,
            )
        ],
        initiative_order=["test_player"],
    )


@pytest.fixture
def mock_context():
    context = AsyncMock(spec=RunContext)
    session_data = AsyncMock(spec=SessionData)
    session_data.player_id = "test_player"
    session_data.location_id = "test_location"
    context.userdata = session_data
    return context


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
    async def test_rows_follow_canonical_declarability(self, mock_context, monkeypatch):
        dependencies = self._dependencies(player={"class": "bard", "level": 1})

        payload = json.loads(await self._read(mock_context, dependencies))
        rows = {row["id"]: row for row in payload["abilities"]}
        assert "combat" not in rows["bard_inspire"]

        monkeypatch.setattr(combat_ability, "condition_ability", lambda _declaration: None)
        payload = json.loads(await self._read(mock_context, dependencies))
        rows = {row["id"]: row for row in payload["abilities"]}

        assert rows["bard_inspire"]["combat"] is False

    @pytest.mark.asyncio
    async def test_every_emitted_row_agrees_with_declaration_gate(self, mock_context):
        catalog = load_fixture_config()
        assert catalog, "ability catalog walk produced no rows"
        emitted_ids = set()
        state = _solo_player_state()

        archetype_ids = {ability.archetype_id for ability in catalog.values()}
        for archetype_id in sorted(archetype_ids):
            class_abilities = [ability for ability in catalog.values() if ability.archetype_id == archetype_id]
            known = [
                {"ability_id": ability.id, "equipped": True}
                for ability in class_abilities
                if ability.ability_type == "elective"
            ]
            for level in sorted({ability.level_requirement for ability in class_abilities}):
                dependencies = self._dependencies(player={"class": archetype_id, "level": level}, known=known)
                payload = json.loads(await self._read(mock_context, dependencies))

                for row in payload["abilities"]:
                    emitted_ids.add(row["id"])
                    published_declarable = row["ability_type"] != "reaction" and row.get("combat") is not False
                    action = row.get("spell_id", row["id"])
                    # The gate resolves an ACTION, and accepts every id it cannot resolve — so for a
                    # spell-backed row (the prompt tells the DM to declare its spell_id) acceptance
                    # alone certifies nothing: a row naming no real spell would pass here and blow up
                    # at resolution instead. Pin the id on the spell catalog the cast path reads.
                    if "spell_id" in row:
                        spells.get_spell(row["spell_id"])
                    try:
                        advance_combat_phase(
                            state,
                            {"test_player": {"type": "ability", "action": action}},
                        )
                    except ValueError:
                        gate_accepted = False
                    else:
                        gate_accepted = True

                    assert gate_accepted is published_declarable, (
                        archetype_id,
                        level,
                        row["id"],
                    )

        assert emitted_ids == set(catalog)

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
