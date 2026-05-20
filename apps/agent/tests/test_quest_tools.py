"""LEVEL_UP payload tests for quest completion — archetype-aware hp_gains."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sample_fixtures import GUILD_PLAYER, level_up_payload, make_context, make_mock_room, mock_txn

from leveling import build_level_up_payload_for_archetype, get_level_up_rewards
from quest_tools import _update_quest_impl

QUEST = {
    "id": "q1",
    "name": "Test Quest",
    "stages": [
        {"id": 0, "objective": "begin", "on_complete": {"xp": 50}},
        {"id": 1, "objective": "middle", "on_complete": {"xp": 100}},
        {"id": 2, "objective": "end", "on_complete": {"xp": 150}},
    ],
}


@pytest.mark.asyncio
async def test_quest_level_up_payload_carries_archetype_hp_gains():
    # Completing stage 1 awards xp 100; player at xp 250 crosses level 1 -> 2.
    player = {
        **GUILD_PLAYER,
        "class": "artificer",
        "xp": 250,
        "attributes": {**GUILD_PLAYER["attributes"], "constitution": 14},
    }
    room = make_mock_room()
    mock_conn = MagicMock()
    mock_db = MagicMock()
    mock_db.transaction = lambda: mock_txn(mock_conn)
    content = MagicMock()
    content.get_quest = AsyncMock(return_value=QUEST)
    content.get_item = AsyncMock(return_value=None)
    queries = MagicMock()
    queries.get_player_quest = AsyncMock(return_value={"current_stage": 1})
    queries.get_player = AsyncMock(return_value=player)
    mutations = MagicMock()
    mutations.set_player_quest = AsyncMock()
    mutations.update_player_xp = AsyncMock()
    mutations.add_inventory_item = AsyncMock()
    ctx = make_context(room=room)

    await _update_quest_impl(ctx, "q1", 2, db_mod=mock_db, mutations=mutations, queries=queries, content=content)

    payload = level_up_payload(room)
    expected = build_level_up_payload_for_archetype(1, get_level_up_rewards(1, 2), "artificer", con_mod=2)
    assert payload is not None
    assert payload["hp_gains"] == expected["hp_gains"]
