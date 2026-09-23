import json
from typing import get_args
from unittest.mock import AsyncMock, MagicMock

import pytest
from archetypes_config_fixture import load_archetype_rows
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod

import archetypes
import db_training
import spells
from leveling import SPELL_TIERS, min_level_for_tier
from training_tools import _initiate_training_cycle_impl, _query_training_programs_impl

ORDINARY_PROGRAM = {
    "id": "combat_basics",
    "name": "Combat Fundamentals",
    "training_activity_type": "technique_base",
}


@pytest.fixture(autouse=True)
def training_activity_read(monkeypatch):
    monkeypatch.setattr(db_training, "get_player_active_training_activities", AsyncMock(return_value=[]))


def _spell_programs() -> list[dict[str, str]]:
    return [
        {
            "id": f"{tier}_study",
            "name": f"{tier.title()} Study",
            "training_activity_type": f"spell_{tier}",
        }
        for tier in sorted(SPELL_TIERS)
    ]


def _dependencies(*, programs=None, player=None, known=None):
    programs = programs or [*_spell_programs(), ORDINARY_PROGRAM]
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


def _all_spells():
    return [spell for source in get_args(spells.SpellSource) for spell in spells.get_spells_by_source(source)]


class TestQueryTrainingPrograms:
    @pytest.mark.asyncio
    async def test_spell_choices_equal_ids_the_start_wall_accepts_for_every_archetype_and_tier(self):
        programs = _spell_programs()
        catalog = _all_spells()
        checked = set()
        mismatches = []
        # Constraint 12's floor: content/spells.json is a corpus this walk reads, so an
        # emptied catalog -- or one tier/source bucket of it -- would agree at [] on both
        # sides and pass vacuously. Every caster row that reaches its floor must offer choices.
        offered_choices = set()
        expect_studiable = set()

        for raw in load_archetype_rows():
            archetype = archetypes.parse_archetype_row(raw["id"], raw)
            for tier in SPELL_TIERS:
                floor = None if archetype.magic_source is None else min_level_for_tier(archetype.id, tier)
                levels = (1, 20) if floor is None else tuple({max(1, floor - 1), floor})
                eligible = next(
                    (
                        spell
                        for spell in catalog
                        if spell.spell_tier == tier
                        and (archetype.magic_source == "cross" or spell.source == archetype.magic_source)
                    ),
                    None,
                )
                known = [] if eligible is None else [{"spell_id": eligible.id}]

                for level in levels:
                    player = {"class": archetype.id, "level": level}
                    content, queries, library = _dependencies(
                        programs=programs,
                        player=player,
                        known=known,
                    )
                    context = make_context()
                    result = json.loads(
                        await _query_training_programs_impl(
                            context,
                            db_content_mod=content,
                            queries_mod=queries,
                            character_spells_mod=library,
                        )
                    )
                    listed = next(row for row in result["programs"] if row["id"] == f"{tier}_study")
                    accepted = set()
                    for spell in catalog:
                        training = MagicMock(
                            get_player_active_training_activities=AsyncMock(return_value=[]),
                            create_training_activity=AsyncMock(return_value="training_id"),
                        )
                        db_mod, _ = make_db_mod()
                        try:
                            await _initiate_training_cycle_impl(
                                context,
                                f"{tier}_study",
                                spell_id=spell.id,
                                db_mod=db_mod,
                                db_training_mod=training,
                                db_content_mod=content,
                                queries_mod=queries,
                                character_spells_mod=library,
                            )
                        except ToolError:
                            pass
                        if training.create_training_activity.await_count:
                            accepted.add(spell.id)

                    if listed["studiable_spell_ids"] != sorted(accepted):
                        mismatches.append((archetype.id, tier, level))
                    if listed["studiable_spell_ids"]:
                        offered_choices.add((archetype.id, tier))
                    if floor is not None and level == floor:
                        expect_studiable.add((archetype.id, tier))
                    if eligible is not None:
                        assert eligible.id not in listed["studiable_spell_ids"]
                        assert eligible.id not in accepted
                checked.add((archetype.id, tier))

        rows = load_archetype_rows()
        assert catalog, "content/spells.json is empty"
        assert mismatches == []
        assert expect_studiable
        assert offered_choices == expect_studiable
        assert len(checked) == len(rows) * len(SPELL_TIERS)
        assert checked == {(row["id"], tier) for row in rows for tier in SPELL_TIERS}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("player", [{}, {"class": "warrior", "level": 5}], ids=["onboarding", "martial"])
    async def test_non_caster_gets_every_program_with_empty_spell_choices(self, player):
        content, queries, library = _dependencies(player=player)
        result = json.loads(
            await _query_training_programs_impl(
                make_context(),
                db_content_mod=content,
                queries_mod=queries,
                character_spells_mod=library,
            )
        )
        rows = {row["id"]: row for row in result["programs"]}
        assert rows[ORDINARY_PROGRAM["id"]] == ORDINARY_PROGRAM
        for program in _spell_programs():
            assert rows[program["id"]] == {**program, "studiable_spell_ids": []}

    @pytest.mark.asyncio
    async def test_returns_persisted_spell_learning_progress(self):
        content, queries, library = _dependencies(player={"class": "mage", "level": 3})
        library.list_learning_progress.return_value = [
            {"spell_id": "arcane_hold_person", "cycles_completed": 1, "cycles_required": 3}
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
        content, queries, library = _dependencies(player=player)
        with pytest.raises(ToolError, match=message):
            await _query_training_programs_impl(
                make_context(),
                db_content_mod=content,
                queries_mod=queries,
                character_spells_mod=library,
            )
