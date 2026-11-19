import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents.llm import ToolError

import event_types as E
from creation_prompts import CREATION_SYSTEM_PROMPT
from creation_tools import finalize_character, push_creation_music
from event_bus import EventBus
from hp_scaling import calculate_max_hp
from rules_engine import attribute_modifier
from session_data import CreationState, SessionData

_finalize: Any = finalize_character._func


def _make_context(creation_state: CreationState | None = None) -> MagicMock:
    """Build a mock RunContext with SessionData containing a creation state."""
    sd = SessionData(
        player_id="test_player",
        location_id="",
        room=None,
        creation_state=creation_state or CreationState(),
    )
    ctx = MagicMock()
    ctx.userdata = sd
    return ctx


class TestFinalizeCharacter:
    async def test_not_in_creation_mode(self):
        ctx = _make_context()
        ctx.userdata.creation_state = None
        with pytest.raises(ToolError):
            await _finalize(ctx)

    @patch("creation_tools.db_session_queries.get_session_init_payload", new_callable=AsyncMock)
    @patch("creation_tools.db_mutations.create_player", new_callable=AsyncMock)
    async def test_finalize_initializes_patron_clock(self, mock_create_player, mock_get_payload):
        mock_get_payload.return_value = {
            "character": {"name": "Aric"},
            "location": None,
            "quests": [],
            "inventory": [],
            "map_progress": [],
            "world_state": {"time": "evening"},
        }

        cs = CreationState(
            phase="identity",
            race="human",
            class_choice="warrior",
            deity="kaelen",
            name="Aric",
            backstory="A wandering sellsword.",
        )
        ctx = _make_context(cs)
        await _finalize(ctx)
        stored = mock_create_player.call_args.args[2]
        served = datetime.fromisoformat(stored["divine_favor"]["last_served_at"])
        assert served.tzinfo is not None
        assert abs((datetime.now(UTC) - served).total_seconds()) < 60

    @patch("creation_tools.db_session_queries.get_session_init_payload", new_callable=AsyncMock)
    @patch("creation_tools.db_mutations.create_player", new_callable=AsyncMock)
    async def test_finalize_starting_hp_from_chassis(self, mock_create_player, mock_get_payload):
        mock_get_payload.return_value = {
            "character": {},
            "location": None,
            "quests": [],
            "inventory": [],
            "map_progress": [],
            "world_state": {},
        }

        cs = CreationState(
            race="human",
            class_choice="warrior",
            deity="kaelen",
            name="Aric",
            backstory="Test.",
        )
        ctx = _make_context(cs)
        _, result = await _finalize(ctx)

        data = mock_create_player.call_args[0][2]
        con_mod = attribute_modifier(data["attributes"]["constitution"])
        expected = calculate_max_hp("warrior", 1, con_mod)
        # Warrior's Endurance (+5) is projected, never stored in hp.max; the follower starts full.
        assert data["hp"] == {"current": expected + 5, "max": expected}
        assert json.loads(result)["character"]["hp"] == {"current": expected + 5, "max": expected + 5}

    @patch("creation_tools.db_mutations.create_player", new_callable=AsyncMock, side_effect=Exception("DB down"))
    async def test_finalize_db_error(self, mock_create_player):
        cs = CreationState(
            race="human",
            class_choice="warrior",
            name="Aric",
        )
        ctx = _make_context(cs)
        with pytest.raises(ToolError):
            await _finalize(ctx)
        assert cs.deity is None


class TestPushCreationMusic:
    async def test_emits_set_music_state_on_event_bus(self):
        bus = EventBus()

        await push_creation_music("wonder", None, bus)

        event = await bus.get(timeout=1.0)
        assert event is not None
        assert event.event_type == E.SET_MUSIC_STATE
        assert event.payload == {"music_state": "wonder"}


class TestCreationPromptDropsMusicTools:
    def test_no_play_sound_or_set_music_state_bullets(self):
        assert "play_sound" not in CREATION_SYSTEM_PROMPT
        assert "set_music_state" not in CREATION_SYSTEM_PROMPT
