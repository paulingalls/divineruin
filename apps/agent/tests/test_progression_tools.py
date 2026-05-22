"""LEVEL_UP payload tests for award_xp — archetype-aware hp_gains."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sample_fixtures import GUILD_PLAYER, level_up_payload, make_context, make_db_mod, make_mock_room

from leveling import build_level_up_payload_for_archetype, get_level_up_rewards
from progression_tools import _award_xp_impl


async def _award_crossing_threshold(player):
    """Award 100 XP to a level-1 player at xp 250, crossing into level 2,
    and return the published LEVEL_UP payload."""
    room = make_mock_room()
    mock_db, _ = make_db_mod()
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value={**player, "xp": 250})
    mutations = MagicMock()
    mutations.update_player_xp = AsyncMock()
    ctx = make_context(room=room)
    await _award_xp_impl(ctx, 100, "quest done", db_mod=mock_db, mutations=mutations, queries=queries)
    return level_up_payload(room)


@pytest.mark.asyncio
async def test_level_up_payload_carries_archetype_hp_gains():
    player = {**GUILD_PLAYER, "class": "artificer", "attributes": {**GUILD_PLAYER["attributes"], "constitution": 14}}
    payload = await _award_crossing_threshold(player)

    expected = build_level_up_payload_for_archetype(1, get_level_up_rewards(1, 2), "artificer", con_mod=2)
    assert payload is not None
    assert payload["hp_gains"] == expected["hp_gains"]


@pytest.mark.asyncio
async def test_level_up_payload_zero_con_mod_still_carries_hp_gains():
    player = {**GUILD_PLAYER, "class": "artificer", "attributes": {**GUILD_PLAYER["attributes"], "constitution": 10}}
    payload = await _award_crossing_threshold(player)

    expected = build_level_up_payload_for_archetype(1, get_level_up_rewards(1, 2), "artificer", con_mod=0)
    assert payload is not None
    assert "hp_gains" in payload
    assert payload["hp_gains"] == expected["hp_gains"]
