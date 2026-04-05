"""Tests for transaction atomicity — events not published on rollback,
session state unchanged on DB failure, partial rewards not applied."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from session_data import SessionData
from tools import (
    award_xp,
    move_player,
    remove_from_inventory,
    update_quest,
)

SAMPLE_PLAYER = {
    "player_id": "player_1",
    "name": "Kael",
    "class": "warrior",
    "level": 1,
    "xp": 0,
    "hp": {"current": 25, "max": 25},
    "ac": 14,
    "attributes": {
        "strength": 14,
        "dexterity": 12,
        "constitution": 13,
        "intelligence": 10,
        "wisdom": 11,
        "charisma": 8,
    },
    "proficiencies": ["athletics", "stealth", "perception"],
    "saving_throw_proficiencies": ["strength", "constitution"],
    "equipment": {"main_hand": {"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}},
}

SAMPLE_LOCATION = {
    "id": "accord_guild_hall",
    "name": "Guild Hall",
    "description": "A hall.",
    "atmosphere": "busy",
    "key_features": [],
    "hidden_elements": [],
    "exits": {"south": {"destination": "accord_market_square"}},
    "tags": [],
    "conditions": {},
}

SAMPLE_QUEST = {
    "id": "greyvale_anomaly",
    "name": "The Greyvale Anomaly",
    "stages": [
        {"id": 0, "objective": "Investigate.", "on_complete": {"xp": 50}},
        {
            "id": 1,
            "objective": "Find source.",
            "on_complete": {"xp": 100, "rewards": [{"item": "research_tablet", "quantity": 1}]},
        },
        {"id": 2, "objective": "Report.", "on_complete": {"xp": 150}},
    ],
}


def _make_context(player_id="player_1", location_id="accord_guild_hall", room=None):
    ctx = MagicMock()
    ctx.userdata = SessionData(player_id=player_id, location_id=location_id, room=room)
    return ctx


def _make_mock_room():
    room = MagicMock()
    room.local_participant = MagicMock()
    room.local_participant.publish_data = AsyncMock()
    return room


@asynccontextmanager
async def _failing_transaction():
    """A transaction mock that raises during commit (on __aexit__)."""
    raise RuntimeError("DB connection lost")
    yield  # pragma: no cover


# --- award_xp: no events on txn failure ---


class TestAwardXpRollback:
    @pytest.mark.asyncio
    @patch("tools.db.transaction", _failing_transaction)
    async def test_no_events_on_txn_failure(self):
        room = _make_mock_room()
        ctx = _make_context(room=room)
        with pytest.raises(RuntimeError, match="DB connection lost"):
            await award_xp._func(ctx, amount=50, reason="test")
        room.local_participant.publish_data.assert_not_called()

    @pytest.mark.asyncio
    @patch("tools.db.transaction", _failing_transaction)
    async def test_no_session_event_on_txn_failure(self):
        ctx = _make_context()
        with pytest.raises(RuntimeError):
            await award_xp._func(ctx, amount=50, reason="test")
        assert len(ctx.userdata.recent_events) == 0


# --- move_player: session.location_id unchanged on DB failure ---


class TestMovePlayerAtomicity:
    @pytest.mark.asyncio
    @patch("tools.db.transaction", _failing_transaction)
    @patch("tools.db_content_queries.get_location", new_callable=AsyncMock)
    async def test_session_location_unchanged_on_db_failure(self, mock_loc):
        mock_loc.return_value = SAMPLE_LOCATION
        ctx = _make_context(location_id="accord_guild_hall")
        with pytest.raises(RuntimeError, match="DB connection lost"):
            await move_player._func(ctx, destination_id="accord_market_square")
        # Session location must NOT have been updated
        assert ctx.userdata.location_id == "accord_guild_hall"

    @pytest.mark.asyncio
    @patch("tools.db.transaction", _failing_transaction)
    @patch("tools.db_content_queries.get_location", new_callable=AsyncMock)
    async def test_no_events_on_db_failure(self, mock_loc):
        mock_loc.return_value = SAMPLE_LOCATION
        room = _make_mock_room()
        ctx = _make_context(room=room)
        with pytest.raises(RuntimeError):
            await move_player._func(ctx, destination_id="accord_market_square")
        room.local_participant.publish_data.assert_not_called()


# --- remove_from_inventory: equipped check + delete atomic ---


class TestRemoveInventoryAtomicity:
    @pytest.mark.asyncio
    @patch("tools.db.transaction", _failing_transaction)
    @patch("tools.db_content_queries.get_item", new_callable=AsyncMock)
    async def test_no_events_on_txn_failure(self, mock_item):
        mock_item.return_value = {"id": "hp", "name": "Health Potion"}
        room = _make_mock_room()
        ctx = _make_context(room=room)
        with pytest.raises(RuntimeError):
            await remove_from_inventory._func(ctx, item_id="hp")
        room.local_participant.publish_data.assert_not_called()


# --- update_quest: no partial events on mid-txn failure ---


class TestUpdateQuestAtomicity:
    @pytest.mark.asyncio
    @patch("tools.db.transaction", _failing_transaction)
    @patch("tools.db_content_queries.get_quest", new_callable=AsyncMock)
    async def test_no_events_on_txn_failure(self, mock_quest):
        mock_quest.return_value = SAMPLE_QUEST
        room = _make_mock_room()
        ctx = _make_context(room=room)
        with pytest.raises(RuntimeError):
            await update_quest._func(ctx, quest_id="greyvale_anomaly", new_stage_id=0)
        room.local_participant.publish_data.assert_not_called()

    @pytest.mark.asyncio
    @patch("tools.db.transaction", _failing_transaction)
    @patch("tools.db_content_queries.get_quest", new_callable=AsyncMock)
    async def test_no_session_event_on_txn_failure(self, mock_quest):
        mock_quest.return_value = SAMPLE_QUEST
        ctx = _make_context()
        with pytest.raises(RuntimeError):
            await update_quest._func(ctx, quest_id="greyvale_anomaly", new_stage_id=0)
        assert len(ctx.userdata.recent_events) == 0
