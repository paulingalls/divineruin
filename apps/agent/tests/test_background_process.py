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
    agent.update_instructions = AsyncMock()
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
        agent.update_instructions.assert_awaited_once()
        call_arg = agent.update_instructions.call_args[0][0]
        assert "WARM CONTENT" in call_arg
        assert bg._last_warm_layer == "WARM CONTENT"

    @patch("background_process.build_warm_layer", new_callable=AsyncMock)
    async def test_skips_if_unchanged(self, mock_build):
        mock_build.return_value = "SAME"
        bg, agent, _ = _make_bg()
        await bg._rebuild_warm_layer()
        agent.update_instructions.reset_mock()
        bg._last_warm_layer = "SAME"
        await bg._rebuild_warm_layer()
        # Should not have called update_instructions since warm layer is the same
        agent.update_instructions.assert_not_awaited()

    @patch("background_process.build_warm_layer", new_callable=AsyncMock)
    async def test_handles_build_failure(self, mock_build):
        mock_build.side_effect = Exception("DB down")
        bg, agent, _ = _make_bg()
        await bg._rebuild_warm_layer()
        agent.update_instructions.assert_not_awaited()


class TestGodWhisperFlow:
    def test_divine_favor_triggers_whisper_queue(self):
        """divine_favor_changed event above threshold queues a CRITICAL god whisper."""
        sd = _make_session_data(patron_id="kaelen")
        bg, _, _ = _make_bg(session_data=sd)
        events = [
            GameEvent(
                event_type="divine_favor_changed",
                payload={"new_level": 25, "last_whisper_level": 0, "patron_id": "kaelen", "reason": "valor"},
            )
        ]
        bg._handle_events(events)
        assert len(bg._speech_queue) == 1
        speech = bg._speech_queue[0]
        assert speech.priority == SpeechPriority.CRITICAL
        assert speech.stinger_sound == "god_whisper_stinger"
        assert "Kaelen" in speech.instructions

    def test_divine_favor_below_threshold_no_whisper(self):
        """divine_favor_changed below threshold does not queue a whisper."""
        sd = _make_session_data(patron_id="kaelen")
        bg, _, _ = _make_bg(session_data=sd)
        events = [
            GameEvent(
                event_type="divine_favor_changed",
                payload={"new_level": 20, "last_whisper_level": 0, "patron_id": "kaelen"},
            )
        ]
        bg._handle_events(events)
        assert len(bg._speech_queue) == 0

    def test_divine_favor_within_cooldown_no_whisper(self):
        """divine_favor_changed within cooldown of last whisper does not queue."""
        sd = _make_session_data(patron_id="syrath")
        bg, _, _ = _make_bg(session_data=sd)
        events = [
            GameEvent(
                event_type="divine_favor_changed",
                payload={"new_level": 40, "last_whisper_level": 25, "patron_id": "syrath"},
            )
        ]
        bg._handle_events(events)
        assert len(bg._speech_queue) == 0

    def test_divine_favor_after_cooldown_triggers(self):
        """divine_favor_changed after cooldown queues a whisper."""
        sd = _make_session_data(patron_id="veythar")
        bg, _, _ = _make_bg(session_data=sd)
        events = [
            GameEvent(
                event_type="divine_favor_changed",
                payload={"new_level": 50, "last_whisper_level": 25, "patron_id": "veythar"},
            )
        ]
        bg._handle_events(events)
        assert len(bg._speech_queue) == 1
        assert "Veythar" in bg._speech_queue[0].instructions

    def test_world_event_god_whisper_queues(self):
        """A world_event with god_whisper prefix queues a CRITICAL whisper."""
        sd = _make_session_data(patron_id="kaelen")
        bg, _, _ = _make_bg(session_data=sd)
        events = [
            GameEvent(
                event_type="world_event",
                payload={"event_id": "god_whisper:player_patron", "patron_id": "kaelen"},
            )
        ]
        bg._handle_events(events)
        assert len(bg._speech_queue) == 1
        assert bg._speech_queue[0].priority == SpeechPriority.CRITICAL
        assert bg._speech_queue[0].stinger_sound == "god_whisper_stinger"

    def test_god_whisper_uses_correct_deity_profile(self):
        """Each deity gets their own personality in the whisper instructions."""
        for deity_id in ["kaelen", "syrath", "veythar"]:
            sd = _make_session_data(patron_id=deity_id)
            bg, _, _ = _make_bg(session_data=sd)
            events = [
                GameEvent(
                    event_type="divine_favor_changed",
                    payload={"new_level": 25, "last_whisper_level": 0, "patron_id": deity_id},
                )
            ]
            bg._handle_events(events)
            assert len(bg._speech_queue) == 1
            instructions = bg._speech_queue[0].instructions
            # Each god's instructions should include their voice character tag
            assert f"GOD_{deity_id.upper()}" in instructions

    async def test_deliver_speech_fires_stinger_before_whisper(self):
        """When delivering a god whisper, the stinger sound fires before generate_reply."""
        sd = _make_session_data(patron_id="kaelen")
        bg, _, session = _make_bg(session_data=sd)
        bg._speech_queue.append(
            PendingSpeech(
                priority=SpeechPriority.CRITICAL,
                instructions="Speak as Kaelen",
                stinger_sound="god_whisper_stinger",
            )
        )
        call_order = []

        async def mock_publish(*args, **kwargs):
            call_order.append("stinger")

        async def mock_reply(**kwargs):
            call_order.append("reply")

        session.generate_reply = mock_reply
        with patch("game_events.publish_game_event", side_effect=mock_publish):
            with patch.dict("sys.modules", {"db": MagicMock()}):
                import db as _db

                _db.get_divine_favor = AsyncMock(return_value={"level": 25})
                _db.mark_favor_whisper_level = AsyncMock()
                await bg._deliver_speech()

        assert call_order == ["stinger", "reply"]
