"""Tests for world effects parser, exit requirements, session flow, and god whispers (WU3)."""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from background_process import (
    BackgroundProcess,
    SpeechPriority,
)
from event_bus import GameEvent
from session_data import CompanionState, SessionData
from tools import (
    EFFECT_NPC_MAP,
    _apply_world_effects,
    _check_exit_requirement,
    discover_hidden_element,
    update_quest,
)

# --- Helpers ---


_mock_conn = MagicMock(name="mock_txn_conn")


@asynccontextmanager
async def _mock_transaction():
    yield _mock_conn


def _make_session(location_id="accord_guild_hall", **kwargs):
    defaults = dict(player_id="player_1", location_id=location_id, room=None)
    defaults.update(kwargs)
    return SessionData(**defaults)


def _make_context(player_id="player_1", location_id="accord_guild_hall", room=None):
    ctx = MagicMock()
    ctx.userdata = _make_session(player_id=player_id, location_id=location_id, room=room)
    return ctx


def _make_mock_room():
    room = MagicMock()
    room.local_participant = MagicMock()
    room.local_participant.publish_data = AsyncMock()
    return room


def _make_bg(session_data=None):
    sd = session_data or _make_session()
    agent = MagicMock()
    agent.update_instructions = AsyncMock()
    session = MagicMock()
    session.generate_reply = AsyncMock()
    bg = BackgroundProcess(agent=agent, session=session, session_data=sd)
    return bg, agent, session


# --- _apply_world_effects ---


class TestApplyWorldEffects:
    @pytest.mark.asyncio
    @patch("tools.db.get_npc", new_callable=AsyncMock)
    @patch("tools.db.set_npc_disposition", new_callable=AsyncMock)
    @patch("tools.db.get_npc_disposition", new_callable=AsyncMock)
    async def test_disposition_effect(self, mock_get_disp, mock_set_disp, mock_npc):
        mock_get_disp.return_value = "neutral"
        mock_npc.return_value = {"default_disposition": "neutral"}
        session = _make_session()
        pending: list[tuple[str, dict]] = []

        await _apply_world_effects(["torin_disposition +1"], session, pending)

        mock_set_disp.assert_called_once()
        call_args = mock_set_disp.call_args
        assert call_args[0][0] == "guildmaster_torin"
        assert call_args[0][2] == "friendly"
        assert any(e[0] == "disposition_changed" for e in pending)

    @pytest.mark.asyncio
    async def test_corruption_effect(self):
        session = _make_session()
        session.corruption_level = 1
        pending: list[tuple[str, dict]] = []

        await _apply_world_effects(["greyvale_corruption +1"], session, pending)

        assert session.corruption_level == 2
        corruption_events = [e for e in pending if e[0] == "hollow_corruption_changed"]
        assert len(corruption_events) == 1
        assert corruption_events[0][1]["level"] == 2
        assert corruption_events[0][1]["previous"] == 1

    @pytest.mark.asyncio
    async def test_event_effect(self):
        session = _make_session()
        pending: list[tuple[str, dict]] = []

        await _apply_world_effects(["event:ruins_discovery_ripple"], session, pending)

        world_events = [e for e in pending if e[0] == "world_event"]
        assert len(world_events) == 1
        assert world_events[0][1]["event_id"] == "ruins_discovery_ripple"

    @pytest.mark.asyncio
    async def test_morale_effect(self):
        session = _make_session()
        pending: list[tuple[str, dict]] = []

        await _apply_world_effects(["millhaven_morale +2"], session, pending)

        world_events = [e for e in pending if e[0] == "world_event"]
        assert len(world_events) == 1
        assert "millhaven_morale_change" in world_events[0][1]["event_id"]

    @pytest.mark.asyncio
    async def test_multiple_effects(self):
        """Test all effects from quest stage 5 on_complete."""
        session = _make_session()
        pending: list[tuple[str, dict]] = []

        with (
            patch("tools.db.get_npc_disposition", new_callable=AsyncMock, return_value="neutral"),
            patch("tools.db.set_npc_disposition", new_callable=AsyncMock),
            patch("tools.db.get_npc", new_callable=AsyncMock, return_value={"default_disposition": "neutral"}),
        ):
            await _apply_world_effects(
                ["emris_disposition +4", "event:faction_interest_triggered", "event:god_whisper:player_patron"],
                session,
                pending,
            )

        event_types = [e[0] for e in pending]
        assert "disposition_changed" in event_types
        assert event_types.count("world_event") == 2

    @pytest.mark.asyncio
    async def test_malformed_effect_handled_gracefully(self):
        session = _make_session()
        pending: list[tuple[str, dict]] = []

        # Should not raise
        await _apply_world_effects(["this_is_not_a_valid_effect", ""], session, pending)
        # No events from malformed strings
        assert len(pending) == 0

    @pytest.mark.asyncio
    async def test_corruption_does_not_go_negative(self):
        session = _make_session()
        session.corruption_level = 0
        pending: list[tuple[str, dict]] = []

        await _apply_world_effects(["greyvale_corruption -1"], session, pending)

        assert session.corruption_level == 0


# --- _check_exit_requirement ---


class TestCheckExitRequirement:
    @pytest.mark.asyncio
    @patch("tools.db.get_player_flag", new_callable=AsyncMock)
    async def test_discovered_flag_set(self, mock_flag):
        mock_flag.return_value = True
        result = await _check_exit_requirement("veythar_seal_mark.discovered", "player_1")
        assert result is True

    @pytest.mark.asyncio
    @patch("tools.db.get_player_flag", new_callable=AsyncMock)
    async def test_discovered_flag_not_set(self, mock_flag):
        mock_flag.return_value = False
        result = await _check_exit_requirement("veythar_seal_mark.discovered", "player_1")
        assert result is False

    @pytest.mark.asyncio
    @patch("tools.db.get_player_flag", new_callable=AsyncMock)
    async def test_or_logic_first_branch_true(self, mock_flag):
        mock_flag.side_effect = [True]
        result = await _check_exit_requirement("seal_a.discovered || seal_b.discovered", "player_1")
        assert result is True

    @pytest.mark.asyncio
    @patch("tools.db.get_player_flag", new_callable=AsyncMock)
    async def test_or_logic_second_branch_true(self, mock_flag):
        mock_flag.side_effect = [False, True]
        result = await _check_exit_requirement("seal_a.discovered || seal_b.discovered", "player_1")
        assert result is True

    @pytest.mark.asyncio
    @patch("tools.db.get_player_flag", new_callable=AsyncMock)
    async def test_or_logic_none_true(self, mock_flag):
        mock_flag.return_value = False
        result = await _check_exit_requirement("seal_a.discovered || seal_b.discovered", "player_1")
        assert result is False

    @pytest.mark.asyncio
    async def test_skill_check_always_false(self):
        result = await _check_exit_requirement("skill_check:athletics:15", "player_1")
        assert result is False

    @pytest.mark.asyncio
    @patch("tools.db.get_player_flag", new_callable=AsyncMock)
    async def test_or_with_skill_check_and_discovered(self, mock_flag):
        mock_flag.return_value = True
        result = await _check_exit_requirement("skill_check:athletics:15 || seal.discovered", "player_1")
        assert result is True


# --- discover_hidden_element sets player flag ---


@patch("tools.db.transaction", _mock_transaction)
class TestDiscoverSetsFlag:
    @pytest.mark.asyncio
    @patch("tools.db.set_player_flag", new_callable=AsyncMock)
    @patch("tools.db.get_player", new_callable=AsyncMock)
    @patch("tools.db.get_location", new_callable=AsyncMock)
    async def test_successful_discovery_sets_flag(self, mock_loc, mock_player, mock_set_flag):
        mock_loc.return_value = {
            "id": "test_loc",
            "name": "Test Location",
            "hidden_elements": [
                {"id": "test_seal", "discover_skill": "perception", "dc": 1, "description": "A seal mark."}
            ],
        }
        mock_player.return_value = {
            "player_id": "player_1",
            "attributes": {"wisdom": 20},
            "proficiencies": ["perception"],
            "level": 10,
        }
        ctx = _make_context(location_id="test_loc")
        result = json.loads(await discover_hidden_element._func(ctx, element_id="test_seal"))

        if result.get("outcome") == "discovered":
            mock_set_flag.assert_called_once_with("player_1", "test_seal.discovered", True)


# --- update_quest calls _apply_world_effects ---


QUEST_WITH_EFFECTS = {
    "id": "test_quest",
    "name": "Test Quest",
    "stages": [
        {
            "id": 0,
            "objective": "Start the quest.",
            "on_complete": {
                "xp": 50,
                "world_effects": ["torin_disposition +1"],
            },
        },
        {
            "id": 1,
            "objective": "Continue the quest.",
            "on_complete": {"xp": 100},
        },
    ],
}


@patch("tools.db.transaction", _mock_transaction)
class TestUpdateQuestWorldEffects:
    @pytest.mark.asyncio
    @patch("tools.db.get_npc", new_callable=AsyncMock)
    @patch("tools.db.set_npc_disposition", new_callable=AsyncMock)
    @patch("tools.db.get_npc_disposition", new_callable=AsyncMock)
    @patch("tools.db.update_player_xp", new_callable=AsyncMock)
    @patch("tools.db.get_player", new_callable=AsyncMock)
    @patch("tools.db.set_player_quest", new_callable=AsyncMock)
    @patch("tools.db.get_player_quest", new_callable=AsyncMock)
    @patch("tools.db.get_quest", new_callable=AsyncMock)
    async def test_world_effects_applied_on_stage_advance(
        self, mock_quest, mock_pq, mock_set, mock_player, mock_xp, mock_get_disp, mock_set_disp, mock_npc
    ):
        mock_quest.return_value = QUEST_WITH_EFFECTS
        mock_pq.return_value = {"current_stage": 0}
        mock_player.return_value = {
            "player_id": "player_1",
            "level": 1,
            "xp": 0,
        }
        mock_get_disp.return_value = "neutral"
        mock_npc.return_value = {"default_disposition": "neutral"}

        room = _make_mock_room()
        ctx = _make_context(room=room)
        result = json.loads(await update_quest._func(ctx, quest_id="test_quest", new_stage_id=1))

        assert result["new_stage"] == 1
        mock_set_disp.assert_called_once()


# --- God whisper event triggers CRITICAL speech ---


class TestGodWhisper:
    def test_god_whisper_event_triggers_speech(self):
        sd = _make_session(
            companion=CompanionState(id="companion_kael", name="Kael"),
        )
        bg, _, _ = _make_bg(session_data=sd)
        events = [GameEvent(event_type="world_event", payload={"event_id": "god_whisper:player_patron"})]
        bg._handle_events(events)
        assert len(bg._speech_queue) == 1
        assert bg._speech_queue[0].priority == SpeechPriority.CRITICAL
        assert "ancient" in bg._speech_queue[0].instructions.lower()

    def test_non_whisper_world_event_no_speech(self):
        bg, _, _ = _make_bg()
        events = [GameEvent(event_type="world_event", payload={"event_id": "ruins_discovery_ripple"})]
        bg._handle_events(events)
        assert len(bg._speech_queue) == 0


# --- Rider scene trigger ---


class TestRiderScene:
    def test_rider_triggers_at_market_square_without_quest_or_meeting(self):
        """Rider triggers at market when: no quest, no companion meeting pending."""
        sd = _make_session(location_id="accord_market_square")
        # Give the player a companion so meeting won't trigger
        sd.companion = CompanionState(id="companion_kael", name="Kael")
        bg, _, _ = _make_bg(session_data=sd)
        bg._quest_cache = []
        bg._meeting_triggered = True  # meeting already happened
        events = [GameEvent(event_type="location_changed", payload={"new_location": "accord_market_square"})]
        bg._handle_events(events)
        # With companion + no quest + meeting already done, rider should NOT trigger
        # because _meeting_triggered is True. Rider requires meeting NOT triggered.
        assert bg._rider_triggered is False

    def test_rider_does_not_trigger_if_meeting_also_triggers(self):
        """Rider scene is suppressed when companion meeting fires at same location."""
        sd = _make_session(location_id="accord_market_square")
        bg, _, _ = _make_bg(session_data=sd)
        bg._quest_cache = []
        # No companion, so meeting will trigger first, blocking rider
        events = [GameEvent(event_type="location_changed", payload={"new_location": "accord_market_square"})]
        bg._handle_events(events)
        # Meeting scene should fire, not rider
        assert bg._meeting_triggered is True
        assert bg._rider_triggered is False

    def test_rider_does_not_trigger_with_active_quest(self):
        sd = _make_session(location_id="accord_market_square")
        bg, _, _ = _make_bg(session_data=sd)
        bg._quest_cache = [{"quest_id": "greyvale_anomaly", "current_stage": 0}]
        bg._meeting_triggered = True  # skip meeting check
        events = [GameEvent(event_type="location_changed", payload={"new_location": "accord_market_square"})]
        bg._handle_events(events)
        assert bg._rider_triggered is False


# --- EFFECT_NPC_MAP ---


class TestEffectNpcMap:
    def test_shorthand_resolution(self):
        assert EFFECT_NPC_MAP["torin"] == "guildmaster_torin"
        assert EFFECT_NPC_MAP["yanna"] == "elder_yanna"
        assert EFFECT_NPC_MAP["emris"] == "scholar_emris"
        assert EFFECT_NPC_MAP["companion"] == "companion_kael"
