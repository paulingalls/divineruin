"""Tests for game state mutation tools (mocked DB + room)."""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from session_data import SessionData
from tools import (
    _clamp_disposition_shift,
    add_to_inventory,
    award_xp,
    move_player,
    remove_from_inventory,
    update_npc_disposition,
    update_quest,
)

SAMPLE_PLAYER = {
    "player_id": "player_1",
    "name": "Kael",
    "class": "warrior",
    "level": 1,
    "xp": 0,
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
    "equipment": {
        "main_hand": {
            "name": "Longsword",
            "damage": "1d8",
            "damage_type": "slashing",
            "properties": [],
        }
    },
    "hp": {"current": 25, "max": 25},
    "ac": 14,
}

SAMPLE_NPC = {
    "id": "guildmaster_torin",
    "name": "Guildmaster Torin",
    "role": "guild hall master",
    "default_disposition": "neutral",
    "voice_notes": "deep baritone",
}

SAMPLE_ITEM = {
    "id": "health_potion",
    "name": "Health Potion",
    "type": "consumable",
    "description": "A glowing red vial.",
    "rarity": "common",
}

SAMPLE_LOCATION = {
    "id": "accord_guild_hall",
    "name": "Guild Hall",
    "description": "Heavy oak doors open onto a hall.",
    "atmosphere": "busy, purposeful",
    "key_features": ["the main counter"],
    "hidden_elements": [],
    "exits": {
        "south": {"destination": "accord_market_square"},
        "east": {"destination": "accord_temple", "requires": "temple_key"},
    },
    "tags": ["guild"],
    "conditions": {},
}

SAMPLE_DESTINATION = {
    "id": "accord_market_square",
    "name": "Market Square",
    "description": "A bustling open-air market.",
    "atmosphere": "noisy, chaotic",
    "key_features": ["merchant stalls"],
    "hidden_elements": [],
    "exits": {"north": {"destination": "accord_guild_hall"}},
    "tags": ["market"],
    "conditions": {},
}

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


# --- Test helpers ---


_mock_conn = MagicMock(name="mock_txn_conn")


@asynccontextmanager
async def _mock_transaction():
    yield _mock_conn


def _make_context(player_id="player_1", location_id="accord_guild_hall", room=None):
    ctx = MagicMock()
    ctx.userdata = SessionData(player_id=player_id, location_id=location_id, room=room)
    return ctx


def _make_mock_room():
    room = MagicMock()
    room.local_participant = MagicMock()
    room.local_participant.publish_data = AsyncMock()
    return room


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


# --- award_xp ---


@patch("tools.db.transaction", _mock_transaction)
class TestAwardXp:
    @pytest.mark.asyncio
    @patch("tools.db.update_player_xp", new_callable=AsyncMock)
    @patch("tools.db.get_player", new_callable=AsyncMock)
    async def test_awards_xp(self, mock_player, mock_update):
        mock_player.return_value = SAMPLE_PLAYER
        ctx = _make_context()
        result = json.loads(await award_xp._func(ctx, amount=50, reason="defeated goblin"))
        assert result["amount"] == 50
        assert result["new_xp"] == 50
        assert result["leveled_up"] is False
        mock_update.assert_called_once_with("player_1", 50, 1, conn=_mock_conn)

    @pytest.mark.asyncio
    @patch("tools.db.update_player_xp", new_callable=AsyncMock)
    @patch("tools.db.get_player", new_callable=AsyncMock)
    async def test_level_up(self, mock_player, mock_update):
        player = {**SAMPLE_PLAYER, "xp": 250}
        mock_player.return_value = player
        ctx = _make_context()
        result = json.loads(await award_xp._func(ctx, amount=100, reason="quest complete"))
        assert result["new_xp"] == 350
        assert result["new_level"] == 2
        assert result["leveled_up"] is True
        mock_update.assert_called_once_with("player_1", 350, 2, conn=_mock_conn)

    @pytest.mark.asyncio
    async def test_negative_amount(self):
        ctx = _make_context()
        result = json.loads(await award_xp._func(ctx, amount=-10, reason="cheat"))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_zero_amount(self):
        ctx = _make_context()
        result = json.loads(await award_xp._func(ctx, amount=0, reason="nothing"))
        assert "error" in result

    @pytest.mark.asyncio
    @patch("tools.db.get_player", new_callable=AsyncMock)
    async def test_missing_player(self, mock_player):
        mock_player.return_value = None
        ctx = _make_context()
        result = json.loads(await award_xp._func(ctx, amount=50, reason="test"))
        assert "error" in result

    @pytest.mark.asyncio
    @patch("tools.db.update_player_xp", new_callable=AsyncMock)
    @patch("tools.db.get_player", new_callable=AsyncMock)
    async def test_publishes_event(self, mock_player, mock_update):
        mock_player.return_value = SAMPLE_PLAYER
        room = _make_mock_room()
        ctx = _make_context(room=room)
        await award_xp._func(ctx, amount=50, reason="test")
        room.local_participant.publish_data.assert_called_once()
        call_data = json.loads(room.local_participant.publish_data.call_args[0][0])
        assert call_data["type"] == "xp_awarded"
        assert call_data["amount"] == 50

    @pytest.mark.asyncio
    @patch("tools.db.update_player_xp", new_callable=AsyncMock)
    @patch("tools.db.get_player", new_callable=AsyncMock)
    async def test_max_level_no_level_up(self, mock_player, mock_update):
        player = {**SAMPLE_PLAYER, "level": 20, "xp": 355000}
        mock_player.return_value = player
        ctx = _make_context()
        result = json.loads(await award_xp._func(ctx, amount=1000, reason="bonus"))
        assert result["new_level"] == 20
        assert result["leveled_up"] is False
        assert result["new_xp"] == 356000


# --- update_npc_disposition ---


@patch("tools.db.transaction", _mock_transaction)
class TestUpdateNpcDisposition:
    @pytest.mark.asyncio
    @patch("tools.db.set_npc_disposition", new_callable=AsyncMock)
    @patch("tools.db.get_npc_disposition", new_callable=AsyncMock)
    @patch("tools.db.get_npc", new_callable=AsyncMock)
    async def test_shift_up(self, mock_npc, mock_disp, mock_set):
        mock_npc.return_value = SAMPLE_NPC
        mock_disp.return_value = "neutral"
        ctx = _make_context()
        result = json.loads(
            await update_npc_disposition._func(ctx, npc_id="guildmaster_torin", delta=1, reason="helped with task")
        )
        assert result["previous"] == "neutral"
        assert result["new"] == "friendly"
        mock_set.assert_called_once()

    @pytest.mark.asyncio
    @patch("tools.db.set_npc_disposition", new_callable=AsyncMock)
    @patch("tools.db.get_npc_disposition", new_callable=AsyncMock)
    @patch("tools.db.get_npc", new_callable=AsyncMock)
    async def test_shift_down(self, mock_npc, mock_disp, mock_set):
        mock_npc.return_value = SAMPLE_NPC
        mock_disp.return_value = "friendly"
        ctx = _make_context()
        result = json.loads(
            await update_npc_disposition._func(ctx, npc_id="guildmaster_torin", delta=-2, reason="insulted them")
        )
        assert result["previous"] == "friendly"
        assert result["new"] == "wary"

    @pytest.mark.asyncio
    @patch("tools.db.set_npc_disposition", new_callable=AsyncMock)
    @patch("tools.db.get_npc_disposition", new_callable=AsyncMock)
    @patch("tools.db.get_npc", new_callable=AsyncMock)
    async def test_clamp_at_top(self, mock_npc, mock_disp, mock_set):
        mock_npc.return_value = SAMPLE_NPC
        mock_disp.return_value = "trusted"
        ctx = _make_context()
        result = json.loads(
            await update_npc_disposition._func(ctx, npc_id="guildmaster_torin", delta=2, reason="saved their life")
        )
        assert result["new"] == "trusted"

    @pytest.mark.asyncio
    @patch("tools.db.set_npc_disposition", new_callable=AsyncMock)
    @patch("tools.db.get_npc_disposition", new_callable=AsyncMock)
    @patch("tools.db.get_npc", new_callable=AsyncMock)
    async def test_clamp_at_bottom(self, mock_npc, mock_disp, mock_set):
        mock_npc.return_value = SAMPLE_NPC
        mock_disp.return_value = "hostile"
        ctx = _make_context()
        result = json.loads(
            await update_npc_disposition._func(ctx, npc_id="guildmaster_torin", delta=-1, reason="attacked them")
        )
        assert result["new"] == "hostile"

    @pytest.mark.asyncio
    @patch("tools.db.get_npc", new_callable=AsyncMock)
    async def test_unknown_npc(self, mock_npc):
        mock_npc.return_value = None
        ctx = _make_context()
        result = json.loads(await update_npc_disposition._func(ctx, npc_id="nobody", delta=1, reason="test"))
        assert "error" in result

    @pytest.mark.asyncio
    @patch("tools.db.set_npc_disposition", new_callable=AsyncMock)
    @patch("tools.db.get_npc_disposition", new_callable=AsyncMock)
    @patch("tools.db.get_npc", new_callable=AsyncMock)
    async def test_falls_back_to_default_disposition(self, mock_npc, mock_disp, mock_set):
        mock_npc.return_value = SAMPLE_NPC
        mock_disp.return_value = None  # no existing disposition
        ctx = _make_context()
        result = json.loads(
            await update_npc_disposition._func(ctx, npc_id="guildmaster_torin", delta=1, reason="first meeting")
        )
        assert result["previous"] == "neutral"
        assert result["new"] == "friendly"

    @pytest.mark.asyncio
    @patch("tools.db.set_npc_disposition", new_callable=AsyncMock)
    @patch("tools.db.get_npc_disposition", new_callable=AsyncMock)
    @patch("tools.db.get_npc", new_callable=AsyncMock)
    async def test_publishes_event(self, mock_npc, mock_disp, mock_set):
        mock_npc.return_value = SAMPLE_NPC
        mock_disp.return_value = "neutral"
        room = _make_mock_room()
        ctx = _make_context(room=room)
        await update_npc_disposition._func(ctx, npc_id="guildmaster_torin", delta=1, reason="helped")
        room.local_participant.publish_data.assert_called_once()
        call_data = json.loads(room.local_participant.publish_data.call_args[0][0])
        assert call_data["type"] == "disposition_changed"
        assert call_data["npc_id"] == "guildmaster_torin"

    @pytest.mark.asyncio
    @patch("tools.db.set_npc_disposition", new_callable=AsyncMock)
    @patch("tools.db.get_npc_disposition", new_callable=AsyncMock)
    @patch("tools.db.get_npc", new_callable=AsyncMock)
    async def test_delta_clamped_to_range(self, mock_npc, mock_disp, mock_set):
        mock_npc.return_value = SAMPLE_NPC
        mock_disp.return_value = "neutral"
        ctx = _make_context()
        result = json.loads(
            await update_npc_disposition._func(ctx, npc_id="guildmaster_torin", delta=5, reason="extreme favor")
        )
        # delta clamped to +2, neutral+2 = trusted
        assert result["new"] == "trusted"


# --- add_to_inventory ---


@patch("tools.db.transaction", _mock_transaction)
class TestAddToInventory:
    @pytest.mark.asyncio
    @patch("tools.db.add_inventory_item", new_callable=AsyncMock)
    @patch("tools.db.get_item", new_callable=AsyncMock)
    async def test_adds_item(self, mock_item, mock_add):
        mock_item.return_value = SAMPLE_ITEM
        ctx = _make_context()
        result = json.loads(await add_to_inventory._func(ctx, item_id="health_potion", quantity=2, source="looted"))
        assert result["action"] == "added"
        assert result["item_name"] == "Health Potion"
        assert result["quantity"] == 2
        mock_add.assert_called_once_with("player_1", "health_potion", 2, conn=_mock_conn)

    @pytest.mark.asyncio
    @patch("tools.db.get_item", new_callable=AsyncMock)
    async def test_unknown_item(self, mock_item):
        mock_item.return_value = None
        ctx = _make_context()
        result = json.loads(await add_to_inventory._func(ctx, item_id="nonexistent", quantity=1, source="found"))
        assert "error" in result

    @pytest.mark.asyncio
    @patch("tools.db.add_inventory_item", new_callable=AsyncMock)
    @patch("tools.db.get_item", new_callable=AsyncMock)
    async def test_publishes_event(self, mock_item, mock_add):
        mock_item.return_value = SAMPLE_ITEM
        room = _make_mock_room()
        ctx = _make_context(room=room)
        await add_to_inventory._func(ctx, item_id="health_potion", quantity=1, source="bought")
        room.local_participant.publish_data.assert_called_once()
        call_data = json.loads(room.local_participant.publish_data.call_args[0][0])
        assert call_data["type"] == "inventory_updated"
        assert call_data["action"] == "added"


# --- remove_from_inventory ---


@patch("tools.db.transaction", _mock_transaction)
class TestRemoveFromInventory:
    @pytest.mark.asyncio
    @patch("tools.db.get_item", new_callable=AsyncMock)
    @patch("tools.db.remove_inventory_item", new_callable=AsyncMock)
    @patch("tools.db.get_inventory_item", new_callable=AsyncMock)
    async def test_removes_item(self, mock_slot, mock_remove, mock_item):
        mock_slot.return_value = {"quantity": 1, "equipped": False}
        mock_remove.return_value = True
        mock_item.return_value = SAMPLE_ITEM
        ctx = _make_context()
        result = json.loads(await remove_from_inventory._func(ctx, item_id="health_potion"))
        assert result["action"] == "removed"
        assert result["item_name"] == "Health Potion"
        mock_remove.assert_called_once()

    @pytest.mark.asyncio
    @patch("tools.db.get_item", new_callable=AsyncMock)
    @patch("tools.db.get_inventory_item", new_callable=AsyncMock)
    async def test_missing_item(self, mock_slot, mock_item):
        mock_slot.return_value = None
        mock_item.return_value = SAMPLE_ITEM
        ctx = _make_context()
        result = json.loads(await remove_from_inventory._func(ctx, item_id="nothing"))
        assert "error" in result

    @pytest.mark.asyncio
    @patch("tools.db.get_item", new_callable=AsyncMock)
    @patch("tools.db.get_inventory_item", new_callable=AsyncMock)
    async def test_equipped_item_blocked(self, mock_slot, mock_item):
        mock_slot.return_value = {"quantity": 1, "equipped": True}
        mock_item.return_value = SAMPLE_ITEM
        ctx = _make_context()
        result = json.loads(await remove_from_inventory._func(ctx, item_id="longsword"))
        assert "error" in result
        assert "equipped" in result["error"].lower()

    @pytest.mark.asyncio
    @patch("tools.db.get_item", new_callable=AsyncMock)
    @patch("tools.db.remove_inventory_item", new_callable=AsyncMock)
    @patch("tools.db.get_inventory_item", new_callable=AsyncMock)
    async def test_publishes_event(self, mock_slot, mock_remove, mock_item):
        mock_slot.return_value = {"quantity": 1, "equipped": False}
        mock_remove.return_value = True
        mock_item.return_value = SAMPLE_ITEM
        room = _make_mock_room()
        ctx = _make_context(room=room)
        await remove_from_inventory._func(ctx, item_id="health_potion")
        room.local_participant.publish_data.assert_called_once()
        call_data = json.loads(room.local_participant.publish_data.call_args[0][0])
        assert call_data["type"] == "inventory_updated"
        assert call_data["action"] == "removed"


# --- move_player ---


@patch("tools.db.transaction", _mock_transaction)
class TestMovePlayer:
    @pytest.mark.asyncio
    @patch("tools.db.get_player", new_callable=AsyncMock)
    @patch("tools.db.get_targets_at_location", new_callable=AsyncMock)
    @patch("tools.db.get_npc_dispositions", new_callable=AsyncMock)
    @patch("tools.db.get_npcs_at_location", new_callable=AsyncMock)
    @patch("tools.db.update_player_location", new_callable=AsyncMock)
    @patch("tools.db.get_location", new_callable=AsyncMock)
    async def test_valid_move(self, mock_loc, mock_update, mock_npcs, mock_disp, mock_targets, mock_player):
        mock_loc.side_effect = [SAMPLE_LOCATION, SAMPLE_DESTINATION]
        mock_npcs.return_value = []
        mock_disp.return_value = {}
        mock_targets.return_value = []
        mock_player.return_value = SAMPLE_PLAYER
        ctx = _make_context()
        result = json.loads(await move_player._func(ctx, destination_id="accord_market_square"))
        assert result["moved"] is True
        assert result["previous_location"] == "accord_guild_hall"
        assert result["location"]["name"] == "Market Square"
        mock_update.assert_called_once_with("player_1", "accord_market_square", conn=_mock_conn)

    @pytest.mark.asyncio
    @patch("tools.db.get_location", new_callable=AsyncMock)
    async def test_invalid_destination(self, mock_loc):
        mock_loc.return_value = SAMPLE_LOCATION
        ctx = _make_context()
        result = json.loads(await move_player._func(ctx, destination_id="nonexistent"))
        assert "error" in result
        assert "valid_destinations" in result

    @pytest.mark.asyncio
    @patch("tools.db.get_location", new_callable=AsyncMock)
    async def test_blocked_exit(self, mock_loc):
        mock_loc.return_value = SAMPLE_LOCATION
        ctx = _make_context()
        result = json.loads(await move_player._func(ctx, destination_id="accord_temple"))
        assert result["blocked"] is True
        assert "requires" in result

    @pytest.mark.asyncio
    @patch("tools.db.get_player", new_callable=AsyncMock)
    @patch("tools.db.get_targets_at_location", new_callable=AsyncMock)
    @patch("tools.db.get_npc_dispositions", new_callable=AsyncMock)
    @patch("tools.db.get_npcs_at_location", new_callable=AsyncMock)
    @patch("tools.db.update_player_location", new_callable=AsyncMock)
    @patch("tools.db.get_location", new_callable=AsyncMock)
    async def test_publishes_event(self, mock_loc, mock_update, mock_npcs, mock_disp, mock_targets, mock_player):
        mock_loc.side_effect = [SAMPLE_LOCATION, SAMPLE_DESTINATION]
        mock_npcs.return_value = []
        mock_disp.return_value = {}
        mock_targets.return_value = []
        mock_player.return_value = SAMPLE_PLAYER
        room = _make_mock_room()
        ctx = _make_context(room=room)
        await move_player._func(ctx, destination_id="accord_market_square")
        room.local_participant.publish_data.assert_called_once()
        call_data = json.loads(room.local_participant.publish_data.call_args[0][0])
        assert call_data["type"] == "location_changed"
        assert call_data["new_location"] == "accord_market_square"

    @pytest.mark.asyncio
    @patch("tools.db.get_player", new_callable=AsyncMock)
    @patch("tools.db.get_targets_at_location", new_callable=AsyncMock)
    @patch("tools.db.get_npc_dispositions", new_callable=AsyncMock)
    @patch("tools.db.get_npcs_at_location", new_callable=AsyncMock)
    @patch("tools.db.update_player_location", new_callable=AsyncMock)
    @patch("tools.db.get_location", new_callable=AsyncMock)
    async def test_session_state_updated(self, mock_loc, mock_update, mock_npcs, mock_disp, mock_targets, mock_player):
        mock_loc.side_effect = [SAMPLE_LOCATION, SAMPLE_DESTINATION]
        mock_npcs.return_value = []
        mock_disp.return_value = {}
        mock_targets.return_value = []
        mock_player.return_value = SAMPLE_PLAYER
        ctx = _make_context()
        await move_player._func(ctx, destination_id="accord_market_square")
        assert ctx.userdata.location_id == "accord_market_square"

    @pytest.mark.asyncio
    @patch("tools.db.get_location", new_callable=AsyncMock)
    async def test_missing_current_location(self, mock_loc):
        mock_loc.return_value = None
        ctx = _make_context()
        result = json.loads(await move_player._func(ctx, destination_id="anywhere"))
        assert "error" in result


# --- update_quest ---


@patch("tools.db.transaction", _mock_transaction)
class TestUpdateQuest:
    @pytest.mark.asyncio
    @patch("tools.db.set_player_quest", new_callable=AsyncMock)
    @patch("tools.db.get_player_quest", new_callable=AsyncMock)
    @patch("tools.db.get_quest", new_callable=AsyncMock)
    async def test_start_quest(self, mock_quest, mock_pq, mock_set):
        mock_quest.return_value = SAMPLE_QUEST
        mock_pq.return_value = None
        ctx = _make_context()
        result = json.loads(await update_quest._func(ctx, quest_id="greyvale_anomaly", new_stage_id=0))
        assert result["new_stage"] == 0
        assert result["quest_name"] == "The Greyvale Anomaly"
        assert result["rewards_applied"] == []
        mock_set.assert_called_once()

    @pytest.mark.asyncio
    @patch("tools.db.get_player_quest", new_callable=AsyncMock)
    @patch("tools.db.get_quest", new_callable=AsyncMock)
    async def test_start_quest_wrong_stage(self, mock_quest, mock_pq):
        mock_quest.return_value = SAMPLE_QUEST
        mock_pq.return_value = None
        ctx = _make_context()
        result = json.loads(await update_quest._func(ctx, quest_id="greyvale_anomaly", new_stage_id=1))
        assert "error" in result

    @pytest.mark.asyncio
    @patch("tools.db.get_item", new_callable=AsyncMock)
    @patch("tools.db.add_inventory_item", new_callable=AsyncMock)
    @patch("tools.db.update_player_xp", new_callable=AsyncMock)
    @patch("tools.db.get_player", new_callable=AsyncMock)
    @patch("tools.db.set_player_quest", new_callable=AsyncMock)
    @patch("tools.db.get_player_quest", new_callable=AsyncMock)
    @patch("tools.db.get_quest", new_callable=AsyncMock)
    async def test_advance_with_rewards(self, mock_quest, mock_pq, mock_set, mock_player, mock_xp, mock_inv, mock_item):
        mock_quest.return_value = SAMPLE_QUEST
        mock_pq.return_value = {"current_stage": 1}
        mock_player.return_value = SAMPLE_PLAYER
        mock_item.return_value = {"id": "research_tablet", "name": "Research Tablet"}
        ctx = _make_context()
        result = json.loads(await update_quest._func(ctx, quest_id="greyvale_anomaly", new_stage_id=2))
        assert result["new_stage"] == 2
        # Stage 1 on_complete: xp=100, items=[research_tablet]
        assert len(result["rewards_applied"]) == 2
        xp_reward = result["rewards_applied"][0]
        assert xp_reward["type"] == "xp"
        assert xp_reward["amount"] == 100
        item_reward = result["rewards_applied"][1]
        assert item_reward["type"] == "item"
        assert item_reward["item_id"] == "research_tablet"
        mock_xp.assert_called_once()
        mock_inv.assert_called_once_with("player_1", "research_tablet", 1, conn=_mock_conn)

    @pytest.mark.asyncio
    @patch("tools.db.get_player_quest", new_callable=AsyncMock)
    @patch("tools.db.get_quest", new_callable=AsyncMock)
    async def test_backward_blocked(self, mock_quest, mock_pq):
        mock_quest.return_value = SAMPLE_QUEST
        mock_pq.return_value = {"current_stage": 1}
        ctx = _make_context()
        result = json.loads(await update_quest._func(ctx, quest_id="greyvale_anomaly", new_stage_id=0))
        assert "error" in result
        assert "backward" in result["error"].lower()

    @pytest.mark.asyncio
    @patch("tools.db.get_player_quest", new_callable=AsyncMock)
    @patch("tools.db.get_quest", new_callable=AsyncMock)
    async def test_skip_stage_blocked(self, mock_quest, mock_pq):
        mock_quest.return_value = SAMPLE_QUEST
        mock_pq.return_value = {"current_stage": 0}
        ctx = _make_context()
        result = json.loads(await update_quest._func(ctx, quest_id="greyvale_anomaly", new_stage_id=2))
        assert "error" in result
        assert "skip" in result["error"].lower()

    @pytest.mark.asyncio
    @patch("tools.db.get_quest", new_callable=AsyncMock)
    async def test_unknown_quest(self, mock_quest):
        mock_quest.return_value = None
        ctx = _make_context()
        result = json.loads(await update_quest._func(ctx, quest_id="nonexistent", new_stage_id=0))
        assert "error" in result

    @pytest.mark.asyncio
    @patch("tools.db.set_player_quest", new_callable=AsyncMock)
    @patch("tools.db.get_player_quest", new_callable=AsyncMock)
    @patch("tools.db.get_quest", new_callable=AsyncMock)
    async def test_publishes_event(self, mock_quest, mock_pq, mock_set):
        mock_quest.return_value = SAMPLE_QUEST
        mock_pq.return_value = None
        room = _make_mock_room()
        ctx = _make_context(room=room)
        await update_quest._func(ctx, quest_id="greyvale_anomaly", new_stage_id=0)
        room.local_participant.publish_data.assert_called_once()
        call_data = json.loads(room.local_participant.publish_data.call_args[0][0])
        assert call_data["type"] == "quest_updated"
        assert call_data["quest_id"] == "greyvale_anomaly"

    @pytest.mark.asyncio
    @patch("tools.db.get_player_quest", new_callable=AsyncMock)
    @patch("tools.db.get_quest", new_callable=AsyncMock)
    async def test_invalid_stage_number(self, mock_quest, mock_pq):
        mock_quest.return_value = SAMPLE_QUEST
        mock_pq.return_value = None
        ctx = _make_context()
        result = json.loads(await update_quest._func(ctx, quest_id="greyvale_anomaly", new_stage_id=99))
        assert "error" in result
