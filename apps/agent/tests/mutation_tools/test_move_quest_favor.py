"""Tests for the move_player, update_quest, and award_divine_favor mutation tools."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import (
    GUILD_PLAYER as SAMPLE_PLAYER,
)
from sample_fixtures import (
    SAMPLE_DESTINATION,
    SAMPLE_LOCATION,
)
from sample_fixtures import (
    make_context as _make_context,
)
from sample_fixtures import (
    make_mock_room as _make_mock_room,
)
from sample_fixtures import (
    mock_txn as _mock_txn,
)

import event_types as E
from movement_tools import _move_player_impl
from progression_tools import _award_divine_favor_impl
from quest_tools import _update_quest_impl

SAMPLE_QUEST = {
    "id": "greyvale_anomaly",
    "name": "The Greyvale Anomaly",
    "stages": [
        {
            "id": 0,
            "objective": "Investigate the strange lights near Greyvale.",
            "on_complete": {"xp": 50},
        },
        {
            "id": 1,
            "objective": "Find the source of the anomaly.",
            "on_complete": {"xp": 100, "rewards": [{"item": "research_tablet", "quantity": 1}]},
        },
        {
            "id": 2,
            "objective": "Report findings to the Guildmaster.",
            "on_complete": {"xp": 150},
        },
    ],
}


class TestMovePlayer:
    def _mocks(self, *, locations=None):
        mock_conn = MagicMock()
        mock_db = MagicMock()
        mock_db.transaction = lambda: _mock_txn(mock_conn)
        from db import extract_exit_connections

        mock_db.extract_exit_connections = extract_exit_connections
        mock_content = MagicMock()
        if locations is not None:
            mock_content.get_location = AsyncMock(side_effect=locations)
        mock_queries = MagicMock()
        mock_queries.get_npcs_at_location = AsyncMock(return_value=[])
        mock_queries.get_npc_dispositions = AsyncMock(return_value={})
        mock_queries.get_targets_at_location = AsyncMock(return_value=[])
        mock_queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        mock_mutations = MagicMock()
        mock_mutations.update_player_location = AsyncMock()
        mock_mutations.upsert_map_progress = AsyncMock()
        return mock_db, mock_content, mock_queries, mock_mutations, mock_conn

    @pytest.mark.asyncio
    async def test_valid_move(self):
        mock_db, mock_content, mock_queries, mock_mutations, mock_conn = self._mocks(
            locations=[SAMPLE_LOCATION, SAMPLE_DESTINATION]
        )
        ctx = _make_context()
        raw = await _move_player_impl(
            ctx,
            "accord_market_square",
            db_mod=mock_db,
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )
        assert isinstance(raw, str)
        result = json.loads(raw)
        assert result["moved"] is True
        assert result["previous_location"] == "accord_guild_hall"
        assert result["location"]["name"] == "Market Square"
        mock_mutations.update_player_location.assert_called_once_with(
            "player_1", "accord_market_square", conn=mock_conn
        )
        mock_mutations.upsert_map_progress.assert_called_once_with(
            "player_1", "accord_market_square", ["accord_guild_hall"], conn=mock_conn
        )

    @pytest.mark.asyncio
    async def test_invalid_destination(self):
        mock_db, mock_content, mock_queries, mock_mutations, _ = self._mocks(locations=[SAMPLE_LOCATION])
        ctx = _make_context()
        with pytest.raises(ToolError, match="No exit"):
            await _move_player_impl(
                ctx,
                "nonexistent",
                db_mod=mock_db,
                mutations=mock_mutations,
                queries=mock_queries,
                content=mock_content,
            )

    @pytest.mark.asyncio
    @patch("movement_tools._check_exit_requirement", new_callable=AsyncMock, return_value=False)
    async def test_blocked_exit(self, mock_check):
        mock_db, mock_content, mock_queries, mock_mutations, _ = self._mocks(locations=[SAMPLE_LOCATION])
        ctx = _make_context()
        raw = await _move_player_impl(
            ctx,
            "accord_temple",
            db_mod=mock_db,
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )
        assert isinstance(raw, str)
        result = json.loads(raw)
        assert result["blocked"] is True
        assert "message" in result
        assert "requires" not in result  # raw requirement strings must not be exposed

    @pytest.mark.asyncio
    async def test_publishes_event(self):
        mock_db, mock_content, mock_queries, mock_mutations, _ = self._mocks(
            locations=[SAMPLE_LOCATION, SAMPLE_DESTINATION]
        )
        room = _make_mock_room()
        ctx = _make_context(room=room)
        await _move_player_impl(
            ctx,
            "accord_market_square",
            db_mod=mock_db,
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )
        room.local_participant.publish_data.assert_called_once()
        call_data = json.loads(room.local_participant.publish_data.call_args[0][0])
        assert call_data["type"] == E.LOCATION_CHANGED
        assert call_data["new_location"] == "accord_market_square"
        assert call_data["location_name"] == "Market Square"
        assert call_data["atmosphere"] == "noisy, chaotic"
        assert call_data["region"] == ""
        assert call_data["connections"] == ["accord_guild_hall"]
        assert call_data["ambient_sounds"] == "market_bustle"

    @pytest.mark.asyncio
    async def test_session_state_updated(self):
        mock_db, mock_content, mock_queries, mock_mutations, _ = self._mocks(
            locations=[SAMPLE_LOCATION, SAMPLE_DESTINATION]
        )
        ctx = _make_context()
        await _move_player_impl(
            ctx,
            "accord_market_square",
            db_mod=mock_db,
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )
        assert ctx.userdata.location_id == "accord_market_square"

    @pytest.mark.asyncio
    async def test_missing_current_location(self):
        mock_db, mock_content, mock_queries, mock_mutations, _ = self._mocks(locations=[None])
        ctx = _make_context()
        with pytest.raises(ToolError, match="Current location"):
            await _move_player_impl(
                ctx,
                "anywhere",
                db_mod=mock_db,
                mutations=mock_mutations,
                queries=mock_queries,
                content=mock_content,
            )


class TestUpdateQuest:
    def _mocks(self, *, quest=SAMPLE_QUEST, player_quest=None):
        mock_conn = MagicMock()
        mock_db = MagicMock()
        mock_db.transaction = lambda: _mock_txn(mock_conn)
        mock_content = MagicMock()
        mock_content.get_quest = AsyncMock(return_value=quest)
        mock_content.get_item = AsyncMock(return_value=None)
        mock_queries = MagicMock()
        mock_queries.get_player_quest = AsyncMock(return_value=player_quest)
        mock_queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        mock_mutations = MagicMock()
        mock_mutations.set_player_quest = AsyncMock()
        mock_mutations.update_player_xp = AsyncMock()
        mock_mutations.add_inventory_item = AsyncMock()
        return mock_db, mock_content, mock_queries, mock_mutations, mock_conn

    async def _call(self, ctx, quest_id, new_stage_id, mocks):
        mock_db, mock_content, mock_queries, mock_mutations, _ = mocks
        raw = await _update_quest_impl(
            ctx,
            quest_id,
            new_stage_id,
            db_mod=mock_db,
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )
        assert isinstance(raw, str)
        return json.loads(raw)

    @pytest.mark.asyncio
    async def test_start_quest(self):
        mocks = self._mocks(player_quest=None)
        ctx = _make_context()
        result = await self._call(ctx, "greyvale_anomaly", 0, mocks)
        assert result["new_stage"] == 0
        assert result["quest_name"] == "The Greyvale Anomaly"
        assert result["rewards_applied"] == []
        mocks[3].set_player_quest.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_quest_wrong_stage(self):
        mocks = self._mocks(player_quest=None)
        ctx = _make_context()
        with pytest.raises(ToolError, match="Must start quest at stage 0"):
            await self._call(ctx, "greyvale_anomaly", 1, mocks)

    @pytest.mark.asyncio
    async def test_advance_with_rewards(self):
        mocks = self._mocks(player_quest={"current_stage": 1})
        _, mock_content, _, mock_mutations, mock_conn = mocks
        mock_content.get_item = AsyncMock(return_value={"id": "research_tablet", "name": "Research Tablet"})
        ctx = _make_context()
        result = await self._call(ctx, "greyvale_anomaly", 2, mocks)
        assert result["new_stage"] == 2
        # Stage 1 on_complete: xp=100, items=[research_tablet]
        assert len(result["rewards_applied"]) == 2
        xp_reward = result["rewards_applied"][0]
        assert xp_reward["type"] == "xp"
        assert xp_reward["amount"] == 100
        item_reward = result["rewards_applied"][1]
        assert item_reward["type"] == "item"
        assert item_reward["item_id"] == "research_tablet"
        mock_mutations.update_player_xp.assert_called_once()
        mock_mutations.add_inventory_item.assert_called_once_with("player_1", "research_tablet", 1, conn=mock_conn)

    @pytest.mark.asyncio
    async def test_backward_blocked(self):
        mocks = self._mocks(player_quest={"current_stage": 1})
        ctx = _make_context()
        with pytest.raises(ToolError, match="backward"):
            await self._call(ctx, "greyvale_anomaly", 0, mocks)

    @pytest.mark.asyncio
    async def test_skip_stage_blocked(self):
        mocks = self._mocks(player_quest={"current_stage": 0})
        ctx = _make_context()
        with pytest.raises(ToolError, match="skip"):
            await self._call(ctx, "greyvale_anomaly", 2, mocks)

    @pytest.mark.asyncio
    async def test_unknown_quest(self):
        mocks = self._mocks(quest=None)
        ctx = _make_context()
        with pytest.raises(ToolError, match="not found"):
            await self._call(ctx, "nonexistent", 0, mocks)

    @pytest.mark.asyncio
    async def test_publishes_event(self):
        mocks = self._mocks(player_quest=None)
        room = _make_mock_room()
        ctx = _make_context(room=room)
        await self._call(ctx, "greyvale_anomaly", 0, mocks)
        room.local_participant.publish_data.assert_called_once()
        call_data = json.loads(room.local_participant.publish_data.call_args[0][0])
        assert call_data["type"] == E.QUEST_UPDATED
        assert call_data["quest_id"] == "greyvale_anomaly"

    @pytest.mark.asyncio
    async def test_invalid_stage_number(self):
        mocks = self._mocks(player_quest=None)
        ctx = _make_context()
        with pytest.raises(ToolError, match="Invalid stage"):
            await self._call(ctx, "greyvale_anomaly", 99, mocks)


SAMPLE_FAVOR = {
    "patron": "kaelen",
    "level": 10,
    "max": 100,
    "last_whisper_level": 0,
}


class TestAwardDivineFavor:
    @pytest.mark.asyncio
    async def test_awards_favor(self):
        mock_conn = MagicMock()
        mock_db = MagicMock()
        mock_db.transaction = lambda: _mock_txn(mock_conn)
        mock_activities = MagicMock()
        mock_activities.get_divine_favor = AsyncMock(return_value=SAMPLE_FAVOR)
        mock_mutations = MagicMock()
        mock_mutations.update_divine_favor = AsyncMock()
        ctx = _make_context()
        result = json.loads(
            await _award_divine_favor_impl(
                ctx, 5, "honored Kaelen", db_mod=mock_db, mutations=mock_mutations, activities=mock_activities
            )
        )
        assert result["patron"] == "kaelen"
        assert result["previous_level"] == 10
        assert result["new_level"] == 15
        assert result["amount"] == 5
        mock_mutations.update_divine_favor.assert_called_once_with("player_1", 15, conn=mock_conn)

    @pytest.mark.asyncio
    async def test_clamps_at_max(self):
        mock_conn = MagicMock()
        mock_db = MagicMock()
        mock_db.transaction = lambda: _mock_txn(mock_conn)
        mock_activities = MagicMock()
        mock_activities.get_divine_favor = AsyncMock(return_value={**SAMPLE_FAVOR, "level": 95})
        mock_mutations = MagicMock()
        mock_mutations.update_divine_favor = AsyncMock()
        ctx = _make_context()
        result = json.loads(
            await _award_divine_favor_impl(
                ctx, 10, "great deed", db_mod=mock_db, mutations=mock_mutations, activities=mock_activities
            )
        )
        assert result["new_level"] == 100
        mock_mutations.update_divine_favor.assert_called_once_with("player_1", 100, conn=mock_conn)

    @pytest.mark.asyncio
    async def test_invalid_amount_too_low(self):
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _award_divine_favor_impl(
                ctx, 0, "test", db_mod=MagicMock(), mutations=MagicMock(), activities=MagicMock()
            )

    @pytest.mark.asyncio
    async def test_invalid_amount_too_high(self):
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _award_divine_favor_impl(
                ctx, 11, "test", db_mod=MagicMock(), mutations=MagicMock(), activities=MagicMock()
            )

    @pytest.mark.asyncio
    async def test_no_patron(self):
        mock_conn = MagicMock()
        mock_db = MagicMock()
        mock_db.transaction = lambda: _mock_txn(mock_conn)
        mock_activities = MagicMock()
        mock_activities.get_divine_favor = AsyncMock(
            return_value={"patron": "none", "level": 0, "max": 100, "last_whisper_level": 0}
        )
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _award_divine_favor_impl(
                ctx, 5, "test", db_mod=mock_db, mutations=MagicMock(), activities=mock_activities
            )

    @pytest.mark.asyncio
    async def test_no_favor_data(self):
        mock_conn = MagicMock()
        mock_db = MagicMock()
        mock_db.transaction = lambda: _mock_txn(mock_conn)
        mock_activities = MagicMock()
        mock_activities.get_divine_favor = AsyncMock(return_value=None)
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _award_divine_favor_impl(
                ctx, 5, "test", db_mod=mock_db, mutations=MagicMock(), activities=mock_activities
            )

    @pytest.mark.asyncio
    async def test_publishes_event(self):
        mock_conn = MagicMock()
        mock_db = MagicMock()
        mock_db.transaction = lambda: _mock_txn(mock_conn)
        mock_activities = MagicMock()
        mock_activities.get_divine_favor = AsyncMock(return_value=SAMPLE_FAVOR)
        mock_mutations = MagicMock()
        mock_mutations.update_divine_favor = AsyncMock()
        room = _make_mock_room()
        ctx = _make_context(room=room)
        await _award_divine_favor_impl(
            ctx, 5, "test", db_mod=mock_db, mutations=mock_mutations, activities=mock_activities
        )
        room.local_participant.publish_data.assert_called_once()
        call_data = json.loads(room.local_participant.publish_data.call_args[0][0])
        assert call_data["type"] == E.DIVINE_FAVOR_CHANGED
        assert call_data["new_level"] == 15
        assert call_data["patron_id"] == "kaelen"
