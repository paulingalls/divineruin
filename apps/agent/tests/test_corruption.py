"""Tests for Hollow corruption tracking (WU2) and related features."""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from background_process import (
    BackgroundProcess,
    SpeechPriority,
)
from event_bus import GameEvent
from prompts import build_warm_layer
from session_data import CompanionState, SessionData
from tools import LOCATION_CORRUPTION, move_player

# --- Helpers ---

SAMPLE_PLAYER = {
    "player_id": "player_1",
    "name": "Test",
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
    "proficiencies": ["athletics", "perception"],
    "saving_throw_proficiencies": ["strength", "constitution"],
    "equipment": {"main_hand": {"name": "Sword", "damage": "1d8", "damage_type": "slashing", "properties": []}},
    "hp": {"current": 25, "max": 25},
    "ac": 14,
}

_mock_conn = MagicMock(name="mock_txn_conn")


@asynccontextmanager
async def _mock_transaction():
    yield _mock_conn


def _make_context(player_id="player_1", location_id="greyvale_wilderness_north", room=None):
    ctx = MagicMock()
    ctx.userdata = SessionData(player_id=player_id, location_id=location_id, room=room)
    return ctx


def _make_mock_room():
    room = MagicMock()
    room.local_participant = MagicMock()
    room.local_participant.publish_data = AsyncMock()
    return room


def _make_bg(session_data=None):
    sd = session_data or SessionData(player_id="player_1", location_id="accord_guild_hall", room=None)
    agent = MagicMock()
    agent.update_instructions = AsyncMock()
    session = MagicMock()
    session.generate_reply = AsyncMock()
    bg = BackgroundProcess(agent=agent, session=session, session_data=sd)
    return bg, agent, session


# --- LOCATION_CORRUPTION mapping ---


class TestLocationCorruption:
    def test_corrupted_locations(self):
        assert LOCATION_CORRUPTION["greyvale_wilderness_north"] == 1
        assert LOCATION_CORRUPTION["hollow_incursion_site"] == 2
        assert LOCATION_CORRUPTION["greyvale_ruins_entrance"] == 2
        assert LOCATION_CORRUPTION["greyvale_ruins_inner"] == 3

    def test_safe_locations_default_to_zero(self):
        assert LOCATION_CORRUPTION.get("accord_guild_hall", 0) == 0
        assert LOCATION_CORRUPTION.get("millhaven", 0) == 0
        assert LOCATION_CORRUPTION.get("accord_market_square", 0) == 0


# --- Corruption updates on move ---


@patch("tools.db.transaction", _mock_transaction)
class TestCorruptionOnMove:
    @pytest.mark.asyncio
    @patch("tools.db.get_player", new_callable=AsyncMock)
    @patch("tools.db.get_targets_at_location", new_callable=AsyncMock)
    @patch("tools.db.get_npc_dispositions", new_callable=AsyncMock)
    @patch("tools.db.get_npcs_at_location", new_callable=AsyncMock)
    @patch("tools.db.update_player_location", new_callable=AsyncMock)
    @patch("tools.db.upsert_map_progress", new_callable=AsyncMock)
    @patch("tools.db.get_location", new_callable=AsyncMock)
    async def test_corruption_increases_on_move_to_corrupted_area(
        self, mock_loc, mock_upsert, mock_update, mock_npcs, mock_disp, mock_targets, mock_player
    ):
        safe_loc = {
            "id": "millhaven",
            "name": "Millhaven",
            "exits": {"north": {"destination": "greyvale_wilderness_north"}},
            "tags": [],
            "conditions": {},
        }
        corrupted_loc = {
            "id": "greyvale_wilderness_north",
            "name": "Northern Wilderness",
            "exits": {"south": {"destination": "millhaven"}},
            "tags": [],
            "conditions": {},
        }
        mock_loc.side_effect = [safe_loc, corrupted_loc]
        mock_npcs.return_value = []
        mock_disp.return_value = {}
        mock_targets.return_value = []
        mock_player.return_value = SAMPLE_PLAYER

        room = _make_mock_room()
        ctx = _make_context(location_id="millhaven", room=room)
        assert ctx.userdata.corruption_level == 0

        result = json.loads(await move_player._func(ctx, destination_id="greyvale_wilderness_north"))
        assert result["moved"] is True
        assert ctx.userdata.corruption_level == 1

        # Verify corruption event was published
        calls = room.local_participant.publish_data.call_args_list
        corruption_events = [
            json.loads(c[0][0]) for c in calls if json.loads(c[0][0]).get("type") == "hollow_corruption_changed"
        ]
        assert len(corruption_events) == 1
        assert corruption_events[0]["level"] == 1
        assert corruption_events[0]["previous"] == 0

    @pytest.mark.asyncio
    @patch("tools.db.get_player", new_callable=AsyncMock)
    @patch("tools.db.get_targets_at_location", new_callable=AsyncMock)
    @patch("tools.db.get_npc_dispositions", new_callable=AsyncMock)
    @patch("tools.db.get_npcs_at_location", new_callable=AsyncMock)
    @patch("tools.db.update_player_location", new_callable=AsyncMock)
    @patch("tools.db.upsert_map_progress", new_callable=AsyncMock)
    @patch("tools.db.get_location", new_callable=AsyncMock)
    async def test_corruption_resets_on_move_to_safe_area(
        self, mock_loc, mock_upsert, mock_update, mock_npcs, mock_disp, mock_targets, mock_player
    ):
        corrupted_loc = {
            "id": "greyvale_wilderness_north",
            "name": "Northern Wilderness",
            "exits": {"south": {"destination": "millhaven"}},
            "tags": [],
            "conditions": {},
        }
        safe_loc = {
            "id": "millhaven",
            "name": "Millhaven",
            "exits": {"north": {"destination": "greyvale_wilderness_north"}},
            "tags": [],
            "conditions": {},
        }
        mock_loc.side_effect = [corrupted_loc, safe_loc]
        mock_npcs.return_value = []
        mock_disp.return_value = {}
        mock_targets.return_value = []
        mock_player.return_value = SAMPLE_PLAYER

        room = _make_mock_room()
        ctx = _make_context(location_id="greyvale_wilderness_north", room=room)
        ctx.userdata.corruption_level = 1

        result = json.loads(await move_player._func(ctx, destination_id="millhaven"))
        assert result["moved"] is True
        assert ctx.userdata.corruption_level == 0


# --- Warm layer includes corruption ---


class TestCorruptionWarmLayer:
    @pytest.mark.asyncio
    @patch("db.get_active_player_quests", new_callable=AsyncMock, return_value=[])
    @patch("db.get_npcs_at_location", new_callable=AsyncMock, return_value=[])
    @patch(
        "db.get_location",
        new_callable=AsyncMock,
        return_value={"name": "Ruins", "description": "Dark.", "atmosphere": "ominous"},
    )
    async def test_corruption_level_1_in_warm_layer(self, _loc, _npcs, _quests):
        warm = await build_warm_layer("ruins", "player_1", "evening", corruption_level=1)
        assert "Stage 1" in warm
        assert "longer silences" in warm

    @pytest.mark.asyncio
    @patch("db.get_active_player_quests", new_callable=AsyncMock, return_value=[])
    @patch("db.get_npcs_at_location", new_callable=AsyncMock, return_value=[])
    @patch(
        "db.get_location",
        new_callable=AsyncMock,
        return_value={"name": "Ruins", "description": "Dark.", "atmosphere": "ominous"},
    )
    async def test_no_corruption_section_at_level_0(self, _loc, _npcs, _quests):
        warm = await build_warm_layer("ruins", "player_1", "evening", corruption_level=0)
        assert "HOLLOW CORRUPTION" not in warm

    @pytest.mark.asyncio
    @patch("db.get_active_player_quests", new_callable=AsyncMock, return_value=[])
    @patch("db.get_npcs_at_location", new_callable=AsyncMock, return_value=[])
    @patch(
        "db.get_location",
        new_callable=AsyncMock,
        return_value={"name": "Ruins", "description": "Dark.", "atmosphere": "ominous"},
    )
    async def test_corruption_level_3_in_warm_layer(self, _loc, _npcs, _quests):
        warm = await build_warm_layer("ruins", "player_1", "evening", corruption_level=3)
        assert "Stage 3" in warm
        assert "subsonic hum" in warm


# --- Background process queues companion speech on corruption change ---


class TestCorruptionBackgroundProcess:
    def test_corruption_change_queues_companion_speech(self):
        sd = SessionData(
            player_id="player_1",
            location_id="greyvale_wilderness_north",
            room=None,
            companion=CompanionState(id="companion_kael", name="Kael"),
        )
        bg, _, _ = _make_bg(session_data=sd)
        events = [
            GameEvent(
                event_type="hollow_corruption_changed",
                payload={"level": 1, "previous": 0, "location_id": "greyvale_wilderness_north"},
            )
        ]
        bg._handle_events(events)
        assert len(bg._speech_queue) == 1
        assert bg._speech_queue[0].priority == SpeechPriority.IMPORTANT

    def test_corruption_level_0_no_speech(self):
        sd = SessionData(
            player_id="player_1",
            location_id="millhaven",
            room=None,
            companion=CompanionState(id="companion_kael", name="Kael"),
        )
        bg, _, _ = _make_bg(session_data=sd)
        events = [
            GameEvent(
                event_type="hollow_corruption_changed", payload={"level": 0, "previous": 1, "location_id": "millhaven"}
            )
        ]
        bg._handle_events(events)
        assert len(bg._speech_queue) == 0

    def test_corruption_triggers_rebuild(self):
        bg, _, _ = _make_bg()
        events = [
            GameEvent(
                event_type="hollow_corruption_changed", payload={"level": 2, "previous": 1, "location_id": "ruins"}
            )
        ]
        assert bg._handle_events(events) is True
