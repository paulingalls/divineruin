"""Tests for BackgroundProcess."""

import time
from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import event_types as E
from background_process import (
    BackgroundProcess,
    PendingSpeech,
    SpeechPriority,
)
from event_bus import GameEvent
from session_data import CombatParticipant, CombatState, CompanionState, SessionData


@contextmanager
def _mock_db_for_warm_layer(quests=None, location=None, npcs=None):
    """Mock the three DB calls used by _rebuild_warm_layer."""
    with patch(
        "background_process.db_queries.get_active_player_quests", new_callable=AsyncMock, return_value=quests or []
    ):
        with patch("background_process.db_content_queries.get_location", new_callable=AsyncMock, return_value=location):
            with patch(
                "background_process.db_queries.get_npcs_at_location", new_callable=AsyncMock, return_value=npcs or []
            ):
                yield


def _make_session_data(**kwargs: object) -> SessionData:
    sd = SessionData(player_id="player_1", location_id="accord_guild_hall")
    for key, value in kwargs.items():
        setattr(sd, key, value)
    return sd


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
        events = [GameEvent(event_type=E.LOCATION_CHANGED, payload={"new_location": "market"})]
        assert bg._handle_events(events) is True

    def test_quest_updated_triggers_rebuild(self):
        bg, _, _ = _make_bg()
        events = [GameEvent(event_type=E.QUEST_UPDATED, payload={"quest_name": "Test"})]
        assert bg._handle_events(events) is True

    def test_disposition_changed_triggers_rebuild(self):
        bg, _, _ = _make_bg()
        events = [GameEvent(event_type=E.DISPOSITION_CHANGED, payload={})]
        assert bg._handle_events(events) is True

    def test_unrelated_event_no_rebuild(self):
        bg, _, _ = _make_bg()
        events = [GameEvent(event_type=E.DICE_ROLL, payload={})]
        assert bg._handle_events(events) is False

    def test_location_changed_queues_speech(self):
        bg, _, _ = _make_bg()
        events = [GameEvent(event_type=E.LOCATION_CHANGED, payload={"new_location": "market"})]
        bg._handle_events(events)
        assert len(bg._speech_queue) == 1
        assert bg._speech_queue[0].priority == SpeechPriority.IMPORTANT

    def test_quest_updated_queues_speech(self):
        bg, _, _ = _make_bg()
        events = [GameEvent(event_type=E.QUEST_UPDATED, payload={"quest_name": "Anomaly", "objective": "Find source"})]
        bg._handle_events(events)
        assert len(bg._speech_queue) == 1
        assert "Anomaly" in bg._speech_queue[0].instructions

    def test_batch_events(self):
        bg, _, _ = _make_bg()
        events = [
            GameEvent(event_type=E.LOCATION_CHANGED, payload={"new_location": "a"}),
            GameEvent(event_type=E.QUEST_UPDATED, payload={"quest_name": "B", "objective": "C"}),
            GameEvent(event_type=E.DICE_ROLL, payload={}),
        ]
        assert bg._handle_events(events) is True
        assert len(bg._speech_queue) == 2


QUEST_WITH_BEATS = {
    "quest_id": "greyvale_anomaly",
    "quest_name": "The Greyvale Anomaly",
    "current_stage": 0,
    "stages": [{"id": "s0", "objective": "Travel."}],
    "scene_graph": [{"scene_id": "scene_road", "stage_refs": [0]}],
}

SCENE_CACHE_FOR_BEATS = {
    "scene_road": {
        "id": "scene_road",
        "name": "Road to Millhaven",
        "type": "quest",
        "region_type": "wilderness",
        "instructions": "Travel narration.",
        "beats": [
            {
                "id": "beat_1",
                "description": "Depart.",
                "completion_condition": "Player travels north",
                "companion_hints": ["Hint A1", "Hint A2"],
                "hint_delay_seconds": 45,
            },
            {
                "id": "beat_2",
                "description": "Unease.",
                "completion_condition": "Player notices quiet",
                "companion_hints": ["Hint B1"],
                "hint_delay_seconds": 60,
            },
        ],
    },
}

QUEST_NO_SCENES = {
    "quest_id": "plain",
    "quest_name": "Plain",
    "current_stage": 0,
    "stages": [{"id": "s0", "objective": "Do stuff."}],
}


class TestCheckSceneBeatHints:
    def test_no_hint_during_combat(self):
        cs = CombatState(
            combat_id="test",
            participants=[
                CombatParticipant(id="p1", name="P", type="player", initiative=10, hp_current=10, hp_max=10, ac=10)
            ],
            initiative_order=["p1"],
        )
        sd = _make_session_data(combat_state=cs, last_player_speech_time=time.time() - 60)
        bg, _, _ = _make_bg(session_data=sd)
        bg._quest_cache = [QUEST_WITH_BEATS]
        bg._scene_cache = SCENE_CACHE_FOR_BEATS
        bg._check_scene_beat_hints()
        assert len(bg._speech_queue) == 0

    def test_no_hint_if_no_speech_time(self):
        sd = _make_session_data(last_player_speech_time=0.0)
        bg, _, _ = _make_bg(session_data=sd)
        bg._quest_cache = [QUEST_WITH_BEATS]
        bg._scene_cache = SCENE_CACHE_FOR_BEATS
        bg._check_scene_beat_hints()
        assert len(bg._speech_queue) == 0

    def _make_sd_with_companion(self, **kwargs):
        defaults = {"last_player_speech_time": time.time() - 50}
        defaults.update(kwargs)
        sd = _make_session_data(**defaults)
        sd.companion = CompanionState(id="companion_kael", name="Kael")
        return sd

    def test_hint_after_beat_delay(self):
        sd = self._make_sd_with_companion()
        bg, _, _ = _make_bg(session_data=sd)
        bg._quest_cache = [QUEST_WITH_BEATS]
        bg._scene_cache = SCENE_CACHE_FOR_BEATS
        bg._check_scene_beat_hints()
        assert len(bg._speech_queue) == 1
        assert bg._speech_queue[0].priority == SpeechPriority.IMPORTANT
        assert "Hint A1" in bg._speech_queue[0].instructions

    def test_no_hint_before_delay(self):
        sd = self._make_sd_with_companion(last_player_speech_time=time.time() - 10)
        bg, _, _ = _make_bg(session_data=sd)
        bg._quest_cache = [QUEST_WITH_BEATS]
        bg._scene_cache = SCENE_CACHE_FOR_BEATS
        bg._check_scene_beat_hints()
        assert len(bg._speech_queue) == 0

    def test_hint_advances_index(self):
        sd = self._make_sd_with_companion()
        bg, _, _ = _make_bg(session_data=sd)
        bg._quest_cache = [QUEST_WITH_BEATS]
        bg._scene_cache = SCENE_CACHE_FOR_BEATS
        # First call delivers hint A1
        bg._check_scene_beat_hints()
        assert len(bg._speech_queue) == 1
        assert "Hint A1" in bg._speech_queue[0].instructions
        bg._speech_queue.clear()
        # Simulate more silence after first hint
        bg._scene_hint_state["last_hint_time"] = time.time() - 50
        bg._check_scene_beat_hints()
        assert len(bg._speech_queue) == 1
        assert "Hint A2" in bg._speech_queue[0].instructions

    def test_beat_advances_when_hints_exhausted(self):
        sd = self._make_sd_with_companion()
        bg, _, _ = _make_bg(session_data=sd)
        bg._quest_cache = [QUEST_WITH_BEATS]
        bg._scene_cache = SCENE_CACHE_FOR_BEATS
        # Deliver all hints from beat 0
        bg._check_scene_beat_hints()  # Hint A1
        bg._speech_queue.clear()
        bg._scene_hint_state["last_hint_time"] = time.time() - 50
        bg._check_scene_beat_hints()  # Hint A2
        bg._speech_queue.clear()
        # hint_index is now 2, which is >= len(hints). Next call advances beat.
        bg._check_scene_beat_hints()
        assert bg._scene_hint_state["beat_index"] == 1
        assert bg._scene_hint_state["hint_index"] == 0

    def test_all_beats_exhausted_no_crash(self):
        past = time.time() - 70
        sd = _make_session_data(last_player_speech_time=past)
        bg, _, _ = _make_bg(session_data=sd)
        bg._quest_cache = [QUEST_WITH_BEATS]
        bg._scene_cache = SCENE_CACHE_FOR_BEATS
        # Exhaust beat 0 (2 hints) + beat 1 (1 hint)
        bg._scene_hint_state = {
            "scene_id": "scene_road",
            "beat_index": 2,  # past all beats
            "hint_index": 0,
            "last_hint_time": 0.0,
        }
        bg._check_scene_beat_hints()
        assert len(bg._speech_queue) == 0

    def test_scene_change_resets_state(self):
        sd = self._make_sd_with_companion()
        bg, _, _ = _make_bg(session_data=sd)
        bg._quest_cache = [QUEST_WITH_BEATS]
        bg._scene_cache = SCENE_CACHE_FOR_BEATS
        # Set stale state from a different scene
        bg._scene_hint_state = {
            "scene_id": "old_scene",
            "beat_index": 5,
            "hint_index": 3,
            "last_hint_time": 0.0,
        }
        bg._check_scene_beat_hints()
        # Should have reset and delivered first hint
        assert bg._scene_hint_state["scene_id"] == "scene_road"
        assert bg._scene_hint_state["beat_index"] == 0
        assert bg._scene_hint_state["hint_index"] == 1  # advanced after delivery
        assert len(bg._speech_queue) == 1
        assert "Hint A1" in bg._speech_queue[0].instructions

    def test_no_hint_without_scenes(self):
        sd = _make_session_data(last_player_speech_time=time.time() - 50)
        bg, _, _ = _make_bg(session_data=sd)
        bg._quest_cache = [QUEST_NO_SCENES]
        bg._check_scene_beat_hints()
        assert len(bg._speech_queue) == 0

    def test_no_hint_with_empty_cache(self):
        sd = _make_session_data(last_player_speech_time=time.time() - 50)
        bg, _, _ = _make_bg(session_data=sd)
        bg._quest_cache = []
        bg._check_scene_beat_hints()
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
        with _mock_db_for_warm_layer(location={"name": "Hall"}):
            await bg._rebuild_warm_layer()
        agent.update_instructions.assert_awaited_once()
        call_arg = agent.update_instructions.call_args[0][0]
        assert "WARM CONTENT" in call_arg
        assert bg._last_warm_layer == "WARM CONTENT"

    @patch("background_process.build_warm_layer", new_callable=AsyncMock)
    async def test_skips_if_unchanged(self, mock_build):
        mock_build.return_value = "SAME"
        bg, agent, _ = _make_bg()
        with _mock_db_for_warm_layer(location={"name": "Hall"}):
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
        with _mock_db_for_warm_layer():
            await bg._rebuild_warm_layer()
        agent.update_instructions.assert_not_awaited()


class TestGodWhisperFlow:
    def test_divine_favor_triggers_whisper_queue(self):
        """divine_favor_changed event above threshold queues a CRITICAL god whisper."""
        sd = _make_session_data(patron_id="kaelen")
        bg, _, _ = _make_bg(session_data=sd)
        events = [
            GameEvent(
                event_type=E.DIVINE_FAVOR_CHANGED,
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
                event_type=E.DIVINE_FAVOR_CHANGED,
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
                event_type=E.DIVINE_FAVOR_CHANGED,
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
                event_type=E.DIVINE_FAVOR_CHANGED,
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
                event_type=E.WORLD_EVENT,
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
                    event_type=E.DIVINE_FAVOR_CHANGED,
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

                _db_mock: Any = _db
                _db_mock.get_divine_favor = AsyncMock(return_value={"level": 25})
                _db_mock.mark_favor_whisper_level = AsyncMock()
                await bg._deliver_speech()

        assert call_order == ["stinger", "reply"]
