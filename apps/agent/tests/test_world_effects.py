from unittest.mock import AsyncMock, MagicMock

import pytest

import event_types as E
from background_process import BackgroundProcess
from event_bus import GameEvent
from movement_tools import _check_exit_requirement
from session_data import SessionData


def _make_session(location_id: str = "accord_guild_hall", player_id: str = "player_1", **kwargs: object) -> SessionData:
    sd = SessionData(player_id=player_id, location_id=location_id)
    for key, value in kwargs.items():
        setattr(sd, key, value)
    return sd


def _make_bg(session_data=None):
    sd = session_data or _make_session()
    agent = MagicMock()
    agent.update_instructions = AsyncMock()
    # The process composes the CURRENT agent's static half, so a mock target must answer with
    # a real string (a MagicMock would not join).
    agent.static_prompt = MagicMock(return_value="STATIC")
    session = MagicMock()
    session.current_agent = agent
    session.generate_reply = AsyncMock()
    bg = BackgroundProcess(session=session, session_data=sd)
    return bg, agent, session


class TestCheckExitRequirement:
    @pytest.mark.asyncio
    async def test_or_logic_first_branch_true(self):
        mock_queries = MagicMock()
        mock_queries.get_player_flag = AsyncMock(side_effect=[True])
        result = await _check_exit_requirement(
            "seal_a.discovered || seal_b.discovered", "player_1", queries=mock_queries
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_or_logic_second_branch_true(self):
        mock_queries = MagicMock()
        mock_queries.get_player_flag = AsyncMock(side_effect=[False, True])
        result = await _check_exit_requirement(
            "seal_a.discovered || seal_b.discovered", "player_1", queries=mock_queries
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_or_logic_none_true(self):
        mock_queries = MagicMock()
        mock_queries.get_player_flag = AsyncMock(return_value=False)
        result = await _check_exit_requirement(
            "seal_a.discovered || seal_b.discovered", "player_1", queries=mock_queries
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_skill_check_always_false(self):
        result = await _check_exit_requirement("skill_check:athletics:15", "player_1")
        assert result is False

    @pytest.mark.asyncio
    async def test_or_with_skill_check_and_discovered(self):
        mock_queries = MagicMock()
        mock_queries.get_player_flag = AsyncMock(return_value=True)
        result = await _check_exit_requirement(
            "skill_check:athletics:15 || seal.discovered", "player_1", queries=mock_queries
        )
        assert result is True


class TestGodWhisper:
    def test_divine_favor_triggers_whisper_at_threshold(self):
        sd = _make_session()
        sd.patron_id = "veythar"
        bg, _, _ = _make_bg(session_data=sd)
        events = [
            GameEvent(
                event_type=E.DIVINE_FAVOR_CHANGED,
                payload={"new_level": 25, "last_whisper_level": 0, "patron_id": "veythar", "amount": 5},
            )
        ]
        bg._handle_events(events)
        assert len(bg._speech_queue) == 1
        assert "GOD_VEYTHAR" in bg._speech_queue[0].instructions

    def test_divine_favor_no_whisper_below_threshold(self):
        sd = _make_session()
        sd.patron_id = "veythar"
        bg, _, _ = _make_bg(session_data=sd)
        events = [
            GameEvent(
                event_type=E.DIVINE_FAVOR_CHANGED,
                payload={"new_level": 20, "last_whisper_level": 0, "patron_id": "veythar", "amount": 5},
            )
        ]
        bg._handle_events(events)
        assert len(bg._speech_queue) == 0

    def test_divine_favor_no_whisper_within_cooldown(self):
        sd = _make_session()
        sd.patron_id = "veythar"
        bg, _, _ = _make_bg(session_data=sd)
        events = [
            GameEvent(
                event_type=E.DIVINE_FAVOR_CHANGED,
                payload={"new_level": 40, "last_whisper_level": 25, "patron_id": "veythar", "amount": 5},
            )
        ]
        bg._handle_events(events)
        assert len(bg._speech_queue) == 0

    def test_non_whisper_world_event_no_speech(self):
        bg, _, _ = _make_bg()
        events = [GameEvent(event_type=E.WORLD_EVENT, payload={"event_id": "ruins_discovery_ripple"})]
        bg._handle_events(events)
        assert len(bg._speech_queue) == 0
