import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from sample_fixtures import mock_txn

import event_types as E
from background_process import BackgroundProcess
from event_bus import GameEvent
from movement_tools import _check_exit_requirement
from quest_tools import _update_quest_impl
from session_data import SessionData

_mock_conn = MagicMock(name="mock_txn_conn")


def _make_session(location_id: str = "accord_guild_hall", player_id: str = "player_1", **kwargs: object) -> SessionData:
    sd = SessionData(player_id=player_id, location_id=location_id)
    for key, value in kwargs.items():
        setattr(sd, key, value)
    return sd


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


class TestUpdateQuestWorldEffects:
    @pytest.mark.asyncio
    async def test_world_effects_applied_on_stage_advance(self):
        mock_db = MagicMock()
        mock_db.transaction = lambda: mock_txn(_mock_conn)
        mock_content = MagicMock()
        mock_content.get_quest = AsyncMock(return_value=QUEST_WITH_EFFECTS)
        mock_content.get_npc = AsyncMock(return_value={"default_disposition": "neutral"})
        mock_content.get_item = AsyncMock(return_value=None)
        mock_queries = MagicMock()
        mock_queries.get_player_quest = AsyncMock(return_value={"current_stage": 0})
        mock_queries.get_player = AsyncMock(
            return_value={
                "player_id": "player_1",
                "level": 1,
                "xp": 0,
            }
        )
        mock_queries.get_npc_disposition = AsyncMock(return_value="neutral")
        mock_mutations = MagicMock()
        mock_mutations.set_player_quest = AsyncMock()
        mock_mutations.update_player_xp = AsyncMock()
        mock_mutations.set_npc_disposition = AsyncMock()

        room = _make_mock_room()
        ctx = _make_context(room=room)
        raw = await _update_quest_impl(
            ctx,
            quest_id="test_quest",
            new_stage_id=1,
            db_mod=mock_db,
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )
        assert isinstance(raw, str)
        result = json.loads(raw)

        assert result["new_stage"] == 1
        mock_mutations.set_npc_disposition.assert_called_once()


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
