from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context

import archetypes
import leveling
import spell_tools


def _queries(archetype_id: str) -> MagicMock:
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value={"player_id": "player_1", "level": 20, "class": archetype_id})
    return queries


async def _learn(archetype_id: str, spell_id: str, records: AsyncMock) -> str:
    return await spell_tools._learn_spell_impl(
        make_context(player_id="player_1"),
        spell_id,
        "discovery",
        queries_mod=_queries(archetype_id),
        character_spells_mod=MagicMock(record_learned=records),
    )


@pytest.mark.asyncio
async def test_cleric_refuses_arcane_and_learns_divine():
    records = AsyncMock()

    with pytest.raises(ToolError) as exc_info:
        await _learn("cleric", "arcane_fireball", records)

    assert "divine" in str(exc_info.value)
    assert "arcane" in str(exc_info.value)
    records.assert_not_awaited()

    await _learn("cleric", "divine_sacred_flame", records)
    records.assert_awaited_once_with("player_1", "divine_sacred_flame", "discovery")


@pytest.mark.parametrize(
    "spell_id",
    ["arcane_spark", "divine_sacred_flame", "primal_druidcraft"],
)
@pytest.mark.asyncio
async def test_bard_learns_from_every_magic_source(spell_id: str):
    records = AsyncMock()

    await _learn("bard", spell_id, records)

    records.assert_awaited_once_with("player_1", spell_id, "discovery")


@pytest.mark.asyncio
async def test_martial_refuses_spell_with_both_sources_named():
    records = AsyncMock()

    with pytest.raises(ToolError) as exc_info:
        await _learn("warrior", "arcane_spark", records)

    assert "no magic source" in str(exc_info.value)
    assert "arcane" in str(exc_info.value)
    records.assert_not_awaited()


def test_every_archetype_with_a_magic_source_has_a_tier_table():
    # learn lets the tier gate's ValueError raise, so a source-holding archetype must never lack a table.
    holders = {a.id for a in archetypes._archetypes.values() if a.magic_source is not None}
    assert holders == set(leveling.MIN_LEVEL_BY_ARCHETYPE_TIER)
