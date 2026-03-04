"""Tests for BackgroundProcess."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

from background_process import (
    BackgroundProcess,
    PendingSpeech,
    SpeechPriority,
)
from event_bus import GameEvent
from session_data import CombatParticipant, CombatState, SessionData


def _make_session_data(**kwargs) -> SessionData:
    defaults = dict(player_id="player_1", location_id="accord_guild_hall", room=None)
    defaults.update(kwargs)
    return SessionData(**defaults)


def _make_bg(session_data=None) -> tuple[BackgroundProcess, MagicMock, MagicMock]:
    sd = session_data or _make_session_data()
    agent = MagicMock()
    agent.instructions = ""
    session = MagicMock()
    session.generate_reply = AsyncMock()
    bg = BackgroundProcess(agent=agent, session=session, session_data=sd)
    return bg, agent, session


class TestHandleEvents:
    def test_location_changed_triggers_rebuild(self):
        bg, _, _ = _make_bg()
        events = [GameEvent(event_type="location_changed", payload={"new_location": "market"})]
        assert bg._handle_events(events) is True

    def test_quest_updated_triggers_rebuild(self):
        bg, _, _ = _make_bg()
        events = [GameEvent(event_type="quest_updated", payload={"quest_name": "Test"})]
        assert bg._handle_events(events) is True

    def test_disposition_changed_triggers_rebuild(self):
        bg, _, _ = _make_bg()
        events = [GameEvent(event_type="disposition_changed", payload={})]
        assert bg._handle_events(events) is True

    def test_unrelated_event_no_rebuild(self):
        bg, _, _ = _make_bg()
        events = [GameEvent(event_type="dice_roll", payload={})]
        assert bg._handle_events(events) is False

    def test_location_changed_queues_speech(self):
        bg, _, _ = _make_bg()
        events = [GameEvent(event_type="location_changed", payload={"new_location": "market"})]
        bg._handle_events(events)
        assert len(bg._speech_queue) == 1
        assert bg._speech_queue[0].priority == SpeechPriority.IMPORTANT

    def test_quest_updated_queues_speech(self):
        bg, _, _ = _make_bg()
        events = [GameEvent(event_type="quest_updated", payload={"quest_name": "Anomaly", "objective": "Find source"})]
        bg._handle_events(events)
        assert len(bg._speech_queue) == 1
        assert "Anomaly" in bg._speech_queue[0].instructions

    def test_batch_events(self):
        bg, _, _ = _make_bg()
        events = [
            GameEvent(event_type="location_changed", payload={"new_location": "a"}),
            GameEvent(event_type="quest_updated", payload={"quest_name": "B", "objective": "C"}),
            GameEvent(event_type="dice_roll", payload={}),
        ]
        assert bg._handle_events(events) is True
        assert len(bg._speech_queue) == 2


class TestCheckGuidance:
    def test_no_nudge_during_combat(self):
        cs = CombatState(
            combat_id="test",
            participants=[
                CombatParticipant(id="p1", name="P", type="player", initiative=10, hp_current=10, hp_max=10, ac=10)
            ],
            initiative_order=["p1"],
        )
        sd = _make_session_data(combat_state=cs, last_player_speech_time=time.time() - 60)
        bg, _, _ = _make_bg(session_data=sd)
        bg._check_guidance()
        assert len(bg._speech_queue) == 0

    def test_no_nudge_if_no_speech_time(self):
        sd = _make_session_data(last_player_speech_time=0.0)
        bg, _, _ = _make_bg(session_data=sd)
        bg._check_guidance()
        assert len(bg._speech_queue) == 0

    def test_nudge_after_level2_silence(self):
        sd = _make_session_data(last_player_speech_time=time.time() - 40)
        bg, _, _ = _make_bg(session_data=sd)
        bg._check_guidance()
        assert len(bg._speech_queue) == 1
        assert bg._speech_queue[0].priority == SpeechPriority.IMPORTANT

    def test_no_nudge_before_level2(self):
        sd = _make_session_data(last_player_speech_time=time.time() - 10)
        bg, _, _ = _make_bg(session_data=sd)
        bg._check_guidance()
        assert len(bg._speech_queue) == 0

    def test_no_repeated_nudge_without_new_speech(self):
        sd = _make_session_data(last_player_speech_time=time.time() - 40)
        bg, _, _ = _make_bg(session_data=sd)
        bg._check_guidance()
        assert len(bg._speech_queue) == 1
        bg._speech_queue.clear()
        # Second check without new player speech should not nudge again
        bg._check_guidance()
        assert len(bg._speech_queue) == 0


class TestDeliverSpeech:
    async def test_delivers_highest_priority(self):
        bg, _, session = _make_bg()
        bg._speech_queue = [
            PendingSpeech(priority=SpeechPriority.ROUTINE, instructions="low"),
            PendingSpeech(priority=SpeechPriority.CRITICAL, instructions="high"),
            PendingSpeech(priority=SpeechPriority.IMPORTANT, instructions="mid"),
        ]
        await bg._deliver_speech()
        session.generate_reply.assert_called_once()
        call_kwargs = session.generate_reply.call_args[1]
        assert call_kwargs["instructions"] == "high"
        assert len(bg._speech_queue) == 0

    async def test_empty_queue_no_op(self):
        bg, _, session = _make_bg()
        await bg._deliver_speech()
        session.generate_reply.assert_not_called()


class TestRebuildWarmLayer:
    @patch("background_process.build_warm_layer", new_callable=AsyncMock)
    async def test_updates_instructions(self, mock_build):
        mock_build.return_value = "WARM CONTENT"
        bg, agent, _ = _make_bg()
        await bg._rebuild_warm_layer()
        assert "WARM CONTENT" in agent.instructions
        assert bg._last_warm_layer == "WARM CONTENT"

    @patch("background_process.build_warm_layer", new_callable=AsyncMock)
    async def test_skips_if_unchanged(self, mock_build):
        mock_build.return_value = "SAME"
        bg, agent, _ = _make_bg()
        await bg._rebuild_warm_layer()
        agent.instructions = "original"
        bg._last_warm_layer = "SAME"
        await bg._rebuild_warm_layer()
        # Should not have changed since warm layer is the same
        assert agent.instructions == "original"

    @patch("background_process.build_warm_layer", new_callable=AsyncMock)
    async def test_handles_build_failure(self, mock_build):
        mock_build.side_effect = Exception("DB down")
        bg, agent, _ = _make_bg()
        agent.instructions = "original"
        await bg._rebuild_warm_layer()
        assert agent.instructions == "original"
