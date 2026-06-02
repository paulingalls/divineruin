"""Tests for game state mutation tools (mocked DB + room)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import (
    GUILD_PLAYER as SAMPLE_PLAYER,
)
from sample_fixtures import (
    SAMPLE_DESTINATION,
    SAMPLE_ITEM,
    SAMPLE_LOCATION,
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
from check_tools import _request_saving_throw_impl, roll_dice
from inventory_tools import _add_to_inventory_impl, _remove_from_inventory_impl
from movement_tools import _move_player_impl
from progression_tools import _award_divine_favor_impl, _award_xp_impl
from quest_tools import _clamp_disposition_shift, _update_quest_impl
from session_tools import _update_npc_disposition_impl
from tool_support import _cap_str, _resolve_ambient_sounds

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


# --- _clamp_disposition_shift ---


class TestClampDispositionShift:
    def test_shift_up(self):
        assert _clamp_disposition_shift("neutral", 1) == "friendly"

    def test_shift_down(self):
        assert _clamp_disposition_shift("neutral", -1) == "wary"

    def test_clamp_at_top(self):
        assert _clamp_disposition_shift("trusted", 2) == "trusted"

    def test_clamp_at_bottom(self):
        assert _clamp_disposition_shift("hostile", -1) == "hostile"

    def test_cautious_normalizes_to_neutral(self):
        # "cautious" shares rank 2 with "neutral" — shifting up from cautious
        assert _clamp_disposition_shift("cautious", 1) == "friendly"

    def test_shift_multiple(self):
        assert _clamp_disposition_shift("hostile", 2) == "neutral"

    def test_unknown_defaults_neutral(self):
        assert _clamp_disposition_shift("unknown", 1) == "friendly"


# --- _resolve_ambient_sounds ---


class TestResolveAmbientSounds:
    def test_daytime_returns_ambient_sounds(self):
        loc = {"ambient_sounds": "market_bustle", "ambient_sounds_night": "harbor_quiet"}
        assert _resolve_ambient_sounds(loc, "evening") == "market_bustle"

    def test_night_returns_night_variant(self):
        loc = {"ambient_sounds": "market_bustle", "ambient_sounds_night": "harbor_quiet"}
        assert _resolve_ambient_sounds(loc, "night") == "harbor_quiet"

    def test_night_without_night_field_falls_back(self):
        loc = {"ambient_sounds": "market_bustle"}
        assert _resolve_ambient_sounds(loc, "night") == "market_bustle"

    def test_missing_ambient_sounds_returns_empty(self):
        loc = {"name": "Some Place"}
        assert _resolve_ambient_sounds(loc, "evening") == ""

    def test_none_location_returns_empty(self):
        assert _resolve_ambient_sounds(None, "evening") == ""

    def test_empty_night_variant_falls_back(self):
        loc = {"ambient_sounds": "market_bustle", "ambient_sounds_night": ""}
        assert _resolve_ambient_sounds(loc, "night") == "market_bustle"


# --- award_xp ---


class TestAwardXp:
    @pytest.mark.asyncio
    async def test_awards_xp(self):
        mock_conn = MagicMock()
        mock_db = MagicMock()
        mock_db.transaction = lambda: _mock_txn(mock_conn)
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        mock_mutations = MagicMock()
        mock_mutations.update_player_xp = AsyncMock()
        ctx = _make_context()
        result = json.loads(
            await _award_xp_impl(
                ctx, 50, "defeated goblin", db_mod=mock_db, mutations=mock_mutations, queries=mock_queries
            )
        )
        assert result["amount"] == 50
        assert result["new_xp"] == 50
        assert result["leveled_up"] is False
        mock_mutations.update_player_xp.assert_called_once_with("player_1", 50, 1, conn=mock_conn)

    @pytest.mark.asyncio
    async def test_level_up(self):
        mock_conn = MagicMock()
        mock_db = MagicMock()
        mock_db.transaction = lambda: _mock_txn(mock_conn)
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value={**SAMPLE_PLAYER, "xp": 250})
        mock_mutations = MagicMock()
        mock_mutations.update_player_xp = AsyncMock()
        ctx = _make_context()
        result = json.loads(
            await _award_xp_impl(
                ctx, 100, "quest complete", db_mod=mock_db, mutations=mock_mutations, queries=mock_queries
            )
        )
        assert result["new_xp"] == 350
        assert result["new_level"] == 2
        assert result["leveled_up"] is True
        mock_mutations.update_player_xp.assert_called_once_with("player_1", 350, 2, conn=mock_conn)

    @pytest.mark.asyncio
    async def test_negative_amount(self):
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _award_xp_impl(ctx, -10, "cheat", db_mod=MagicMock(), mutations=MagicMock(), queries=MagicMock())

    @pytest.mark.asyncio
    async def test_zero_amount(self):
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _award_xp_impl(ctx, 0, "nothing", db_mod=MagicMock(), mutations=MagicMock(), queries=MagicMock())

    @pytest.mark.asyncio
    async def test_missing_player(self):
        mock_conn = MagicMock()
        mock_db = MagicMock()
        mock_db.transaction = lambda: _mock_txn(mock_conn)
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value=None)
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _award_xp_impl(ctx, 50, "test", db_mod=mock_db, mutations=MagicMock(), queries=mock_queries)

    @pytest.mark.asyncio
    async def test_publishes_event(self):
        mock_conn = MagicMock()
        mock_db = MagicMock()
        mock_db.transaction = lambda: _mock_txn(mock_conn)
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        mock_mutations = MagicMock()
        mock_mutations.update_player_xp = AsyncMock()
        room = _make_mock_room()
        ctx = _make_context(room=room)
        await _award_xp_impl(ctx, 50, "test", db_mod=mock_db, mutations=mock_mutations, queries=mock_queries)
        room.local_participant.publish_data.assert_called_once()
        call_data = json.loads(room.local_participant.publish_data.call_args[0][0])
        assert call_data["type"] == E.XP_AWARDED
        assert call_data["amount"] == 50

    @pytest.mark.asyncio
    async def test_max_level_no_level_up(self):
        mock_conn = MagicMock()
        mock_db = MagicMock()
        mock_db.transaction = lambda: _mock_txn(mock_conn)
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value={**SAMPLE_PLAYER, "level": 20, "xp": 355000})
        mock_mutations = MagicMock()
        mock_mutations.update_player_xp = AsyncMock()
        ctx = _make_context()
        result = json.loads(
            await _award_xp_impl(ctx, 1000, "bonus", db_mod=mock_db, mutations=mock_mutations, queries=mock_queries)
        )
        assert result["new_level"] == 20
        assert result["leveled_up"] is False
        assert result["new_xp"] == 356000


# --- update_npc_disposition ---


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


# --- add_to_inventory ---


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


# --- remove_from_inventory ---


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


# --- move_player ---


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


# --- update_quest ---


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


# --- award_divine_favor ---


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


# --- _cap_str ---


class TestCapStr:
    def test_returns_none_within_limit(self):
        assert _cap_str("hello", 10, "test") is None

    def test_returns_error_over_limit(self):
        with pytest.raises(ToolError, match="256"):
            _cap_str("x" * 300, 256, "reason")

    def test_exact_boundary_is_ok(self):
        assert _cap_str("x" * 256, 256, "reason") is None


# --- String and integer bounds ---


class TestStringCaps:
    @pytest.mark.asyncio
    async def test_award_xp_reason_too_long(self):
        ctx = _make_context()
        with pytest.raises(ToolError, match="reason"):
            await _award_xp_impl(ctx, 50, "x" * 300, db_mod=MagicMock(), mutations=MagicMock(), queries=MagicMock())

    @pytest.mark.asyncio
    async def test_award_divine_favor_reason_too_long(self):
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _award_divine_favor_impl(
                ctx, 5, "x" * 300, db_mod=MagicMock(), mutations=MagicMock(), activities=MagicMock()
            )

    @pytest.mark.asyncio
    async def test_update_npc_disposition_reason_too_long(self):
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _update_npc_disposition_impl(
                ctx,
                "guildmaster_torin",
                1,
                "x" * 300,
                db_mod=MagicMock(),
                mutations=MagicMock(),
                queries=MagicMock(),
                content=MagicMock(),
            )

    @pytest.mark.asyncio
    async def test_add_to_inventory_source_too_long(self):
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _add_to_inventory_impl(
                ctx,
                "health_potion",
                1,
                "x" * 300,
                db_mod=MagicMock(),
                mutations=MagicMock(),
                queries=MagicMock(),
                content=MagicMock(),
            )

    @pytest.mark.asyncio
    async def test_roll_dice_notation_too_long(self):
        ctx = _make_context()
        with pytest.raises(ToolError):
            await roll_dice._func(ctx, notation="x" * 60)


class TestIntegerBounds:
    @pytest.mark.asyncio
    async def test_award_xp_exceeds_max(self):
        ctx = _make_context()
        with pytest.raises(ToolError, match="10000"):
            await _award_xp_impl(ctx, 10001, "too much", db_mod=MagicMock(), mutations=MagicMock(), queries=MagicMock())

    @pytest.mark.asyncio
    async def test_award_xp_at_max_is_ok(self):
        """10000 should be accepted (boundary value)."""
        mock_conn = MagicMock()
        mock_db = MagicMock()
        mock_db.transaction = lambda: _mock_txn(mock_conn)
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        mock_mutations = MagicMock()
        mock_mutations.update_player_xp = AsyncMock()
        # A 10000-XP jump levels the skirmisher across L10/L15, so award_xp legitimately
        # applies the crossed auto-grant flags (e.g. extra_attack) via set_player_flag.
        mock_mutations.set_player_flag = AsyncMock()
        ctx = _make_context()
        result = json.loads(
            await _award_xp_impl(
                ctx, 10000, "big reward", db_mod=mock_db, mutations=mock_mutations, queries=mock_queries
            )
        )
        assert "error" not in result
        assert result["amount"] == 10000

    @pytest.mark.asyncio
    async def test_add_to_inventory_quantity_zero(self):
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _add_to_inventory_impl(
                ctx,
                "health_potion",
                0,
                "test",
                db_mod=MagicMock(),
                mutations=MagicMock(),
                queries=MagicMock(),
                content=MagicMock(),
            )

    @pytest.mark.asyncio
    async def test_add_to_inventory_quantity_100(self):
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _add_to_inventory_impl(
                ctx,
                "health_potion",
                100,
                "test",
                db_mod=MagicMock(),
                mutations=MagicMock(),
                queries=MagicMock(),
                content=MagicMock(),
            )

    @pytest.mark.asyncio
    async def test_saving_throw_dc_zero(self):
        ctx = _make_context()
        with pytest.raises(ToolError, match="DC"):
            await _request_saving_throw_impl(ctx, "strength", 0, "knocked prone", queries=MagicMock())

    @pytest.mark.asyncio
    async def test_saving_throw_dc_31(self):
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _request_saving_throw_impl(ctx, "dexterity", 31, "fireball", queries=MagicMock())
