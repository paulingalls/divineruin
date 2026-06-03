"""Tests for the NPC-disposition and inventory mutation tools (mocked DB + room)."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import (
    SAMPLE_ITEM,
    SAMPLE_NPC,
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
from inventory_tools import _add_to_inventory_impl, _remove_from_inventory_impl
from session_tools import _update_npc_disposition_impl


class TestUpdateNpcDisposition:
    def _mocks(self, *, npc=SAMPLE_NPC, disp: str | None = "neutral"):
        mock_conn = MagicMock()
        mock_db = MagicMock()
        mock_db.transaction = lambda: _mock_txn(mock_conn)
        mock_content = MagicMock()
        mock_content.get_npc = AsyncMock(return_value=npc)
        mock_queries = MagicMock()
        mock_queries.get_npc_disposition = AsyncMock(return_value=disp)
        mock_mutations = MagicMock()
        mock_mutations.set_npc_disposition = AsyncMock()
        return mock_db, mock_content, mock_queries, mock_mutations

    async def _call(self, ctx, npc_id, delta, reason, mocks):
        mock_db, mock_content, mock_queries, mock_mutations = mocks
        return json.loads(
            await _update_npc_disposition_impl(
                ctx,
                npc_id,
                delta,
                reason,
                db_mod=mock_db,
                mutations=mock_mutations,
                queries=mock_queries,
                content=mock_content,
            )
        )

    @pytest.mark.asyncio
    async def test_shift_up(self):
        mocks = self._mocks(disp="neutral")
        ctx = _make_context()
        result = await self._call(ctx, "guildmaster_torin", 1, "helped with task", mocks)
        assert result["previous"] == "neutral"
        assert result["new"] == "friendly"
        mocks[3].set_npc_disposition.assert_called_once()

    @pytest.mark.asyncio
    async def test_shift_down(self):
        mocks = self._mocks(disp="friendly")
        ctx = _make_context()
        result = await self._call(ctx, "guildmaster_torin", -2, "insulted them", mocks)
        assert result["previous"] == "friendly"
        assert result["new"] == "wary"

    @pytest.mark.asyncio
    async def test_clamp_at_top(self):
        mocks = self._mocks(disp="trusted")
        ctx = _make_context()
        result = await self._call(ctx, "guildmaster_torin", 2, "saved their life", mocks)
        assert result["new"] == "trusted"

    @pytest.mark.asyncio
    async def test_clamp_at_bottom(self):
        mocks = self._mocks(disp="hostile")
        ctx = _make_context()
        result = await self._call(ctx, "guildmaster_torin", -1, "attacked them", mocks)
        assert result["new"] == "hostile"

    @pytest.mark.asyncio
    async def test_unknown_npc(self):
        mocks = self._mocks(npc=None)
        ctx = _make_context()
        with pytest.raises(ToolError, match="not found"):
            await self._call(ctx, "nobody", 1, "test", mocks)

    @pytest.mark.asyncio
    async def test_falls_back_to_default_disposition(self):
        mocks = self._mocks(disp=None)
        ctx = _make_context()
        result = await self._call(ctx, "guildmaster_torin", 1, "first meeting", mocks)
        assert result["previous"] == "neutral"
        assert result["new"] == "friendly"

    @pytest.mark.asyncio
    async def test_publishes_event(self):
        mocks = self._mocks(disp="neutral")
        room = _make_mock_room()
        ctx = _make_context(room=room)
        await self._call(ctx, "guildmaster_torin", 1, "helped", mocks)
        room.local_participant.publish_data.assert_called_once()
        call_data = json.loads(room.local_participant.publish_data.call_args[0][0])
        assert call_data["type"] == E.DISPOSITION_CHANGED
        assert call_data["npc_id"] == "guildmaster_torin"

    @pytest.mark.asyncio
    async def test_delta_clamped_to_range(self):
        mocks = self._mocks(disp="neutral")
        ctx = _make_context()
        result = await self._call(ctx, "guildmaster_torin", 5, "extreme favor", mocks)
        # delta clamped to +2, neutral+2 = trusted
        assert result["new"] == "trusted"


class TestAddToInventory:
    @pytest.mark.asyncio
    async def test_adds_item(self):
        mock_conn = MagicMock()
        mock_db = MagicMock()
        mock_db.transaction = lambda: _mock_txn(mock_conn)
        mock_content = MagicMock()
        mock_content.get_item = AsyncMock(return_value=SAMPLE_ITEM)
        mock_mutations = MagicMock()
        mock_mutations.add_inventory_item = AsyncMock()
        mock_queries = MagicMock()
        mock_queries.get_player_inventory = AsyncMock(return_value=[SAMPLE_ITEM])
        ctx = _make_context()
        result = json.loads(
            await _add_to_inventory_impl(
                ctx,
                "health_potion",
                2,
                "looted",
                db_mod=mock_db,
                mutations=mock_mutations,
                queries=mock_queries,
                content=mock_content,
            )
        )
        assert result["action"] == "added"
        assert result["item_name"] == "Health Potion"
        assert result["quantity"] == 2
        mock_mutations.add_inventory_item.assert_called_once_with("player_1", "health_potion", 2, conn=mock_conn)

    @pytest.mark.asyncio
    async def test_unknown_item(self):
        mock_conn = MagicMock()
        mock_db = MagicMock()
        mock_db.transaction = lambda: _mock_txn(mock_conn)
        mock_content = MagicMock()
        mock_content.get_item = AsyncMock(return_value=None)
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _add_to_inventory_impl(
                ctx,
                "nonexistent",
                1,
                "found",
                db_mod=mock_db,
                mutations=MagicMock(),
                queries=MagicMock(),
                content=mock_content,
            )

    @pytest.mark.asyncio
    async def test_publishes_event(self):
        from db import _compute_item_image_url

        mock_conn = MagicMock()
        mock_db = MagicMock()
        mock_db.transaction = lambda: _mock_txn(mock_conn)
        mock_db._compute_item_image_url = _compute_item_image_url
        mock_content = MagicMock()
        mock_content.get_item = AsyncMock(return_value=SAMPLE_ITEM)
        mock_mutations = MagicMock()
        mock_mutations.add_inventory_item = AsyncMock()
        mock_queries = MagicMock()
        mock_queries.get_player_inventory = AsyncMock(return_value=[SAMPLE_ITEM])
        room = _make_mock_room()
        ctx = _make_context(room=room)
        await _add_to_inventory_impl(
            ctx,
            "health_potion",
            1,
            "bought",
            db_mod=mock_db,
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )
        # Two events: inventory_updated + item_acquired
        assert room.local_participant.publish_data.call_count == 2
        first_call = json.loads(room.local_participant.publish_data.call_args_list[0][0][0])
        assert first_call["type"] == E.INVENTORY_UPDATED
        assert "inventory" in first_call
        second_call = json.loads(room.local_participant.publish_data.call_args_list[1][0][0])
        assert second_call["type"] == E.ITEM_ACQUIRED


class TestRemoveFromInventory:
    @pytest.mark.asyncio
    async def test_removes_item(self):
        mock_conn = MagicMock()
        mock_db = MagicMock()
        mock_db.transaction = lambda: _mock_txn(mock_conn)
        mock_content = MagicMock()
        mock_content.get_item = AsyncMock(return_value=SAMPLE_ITEM)
        mock_queries = MagicMock()
        mock_queries.get_inventory_item = AsyncMock(return_value={"quantity": 1, "equipped": False})
        mock_mutations = MagicMock()
        mock_mutations.remove_inventory_item = AsyncMock(return_value=True)
        ctx = _make_context()
        result = json.loads(
            await _remove_from_inventory_impl(
                ctx,
                "health_potion",
                db_mod=mock_db,
                mutations=mock_mutations,
                queries=mock_queries,
                content=mock_content,
            )
        )
        assert result["action"] == "removed"
        assert result["item_name"] == "Health Potion"
        mock_mutations.remove_inventory_item.assert_called_once()

    @pytest.mark.asyncio
    async def test_missing_item(self):
        mock_conn = MagicMock()
        mock_db = MagicMock()
        mock_db.transaction = lambda: _mock_txn(mock_conn)
        mock_content = MagicMock()
        mock_content.get_item = AsyncMock(return_value=SAMPLE_ITEM)
        mock_queries = MagicMock()
        mock_queries.get_inventory_item = AsyncMock(return_value=None)
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _remove_from_inventory_impl(
                ctx,
                "nothing",
                db_mod=mock_db,
                mutations=MagicMock(),
                queries=mock_queries,
                content=mock_content,
            )

    @pytest.mark.asyncio
    async def test_equipped_item_blocked(self):
        mock_conn = MagicMock()
        mock_db = MagicMock()
        mock_db.transaction = lambda: _mock_txn(mock_conn)
        mock_content = MagicMock()
        mock_content.get_item = AsyncMock(return_value=SAMPLE_ITEM)
        mock_queries = MagicMock()
        mock_queries.get_inventory_item = AsyncMock(return_value={"quantity": 1, "equipped": True})
        ctx = _make_context()
        with pytest.raises(ToolError, match="equipped"):
            await _remove_from_inventory_impl(
                ctx,
                "longsword",
                db_mod=mock_db,
                mutations=MagicMock(),
                queries=mock_queries,
                content=mock_content,
            )

    @pytest.mark.asyncio
    async def test_publishes_event(self):
        mock_conn = MagicMock()
        mock_db = MagicMock()
        mock_db.transaction = lambda: _mock_txn(mock_conn)
        mock_content = MagicMock()
        mock_content.get_item = AsyncMock(return_value=SAMPLE_ITEM)
        mock_queries = MagicMock()
        mock_queries.get_inventory_item = AsyncMock(return_value={"quantity": 1, "equipped": False})
        mock_mutations = MagicMock()
        mock_mutations.remove_inventory_item = AsyncMock(return_value=True)
        room = _make_mock_room()
        ctx = _make_context(room=room)
        await _remove_from_inventory_impl(
            ctx,
            "health_potion",
            db_mod=mock_db,
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )
        room.local_participant.publish_data.assert_called_once()
        call_data = json.loads(room.local_participant.publish_data.call_args[0][0])
        assert call_data["type"] == E.INVENTORY_UPDATED
        assert call_data["action"] == "removed"
