"""Tests for proactive companion speech: event reactions, idle speech, quest hints, emotional state."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

import event_types as E
from background_process import BackgroundProcess
from bg_speech import COMPANION_IDLE_SECS, SpeechPriority
from event_bus import GameEvent
from session_data import CombatParticipant, CombatState, CompanionState, SessionData


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


class TestCompanionSpeechInEvents:
    def test_location_changed_with_companion_mentions_kael(self):
        sd = _make_session_data()
        sd.companion = CompanionState(id="companion_kael", name="Kael", last_speech_time=time.time())
        bg, _, _ = _make_bg(session_data=sd)
        events = [GameEvent(event_type=E.LOCATION_CHANGED, payload={"new_location": "market"})]
        bg._handle_events(events)
        assert len(bg._speech_queue) == 1
        assert "COMPANION_KAEL" in bg._speech_queue[0].instructions

    def test_location_changed_without_companion_no_kael(self):
        sd = _make_session_data()
        bg, _, _ = _make_bg(session_data=sd)
        events = [GameEvent(event_type=E.LOCATION_CHANGED, payload={"new_location": "market"})]
        bg._handle_events(events)
        assert len(bg._speech_queue) == 1
        assert "COMPANION_KAEL" not in bg._speech_queue[0].instructions

    def test_quest_updated_with_companion(self):
        sd = _make_session_data()
        sd.companion = CompanionState(id="companion_kael", name="Kael")
        bg, _, _ = _make_bg(session_data=sd)
        events = [GameEvent(event_type=E.QUEST_UPDATED, payload={"quest_name": "Test", "objective": "Do thing"})]
        bg._handle_events(events)
        assert "COMPANION_KAEL" in bg._speech_queue[0].instructions

    def test_combat_ended_victory_with_companion(self):
        sd = _make_session_data()
        sd.companion = CompanionState(id="companion_kael", name="Kael")
        bg, _, _ = _make_bg(session_data=sd)
        events = [GameEvent(event_type=E.COMBAT_ENDED, payload={"outcome": "victory"})]
        bg._handle_events(events)
        assert "COMPANION_KAEL" in bg._speech_queue[0].instructions
        assert sd.companion.emotional_state == "relieved"

    def test_combat_ended_victory_restores_unconscious_companion(self):
        sd = _make_session_data()
        sd.companion = CompanionState(id="companion_kael", name="Kael", is_conscious=False)
        bg, _, _ = _make_bg(session_data=sd)
        events = [GameEvent(event_type=E.COMBAT_ENDED, payload={"outcome": "victory"})]
        bg._handle_events(events)
        assert sd.companion.is_conscious is True
        assert sd.companion.emotional_state == "weary"

    def test_disposition_changed_with_companion(self):
        sd = _make_session_data()
        sd.companion = CompanionState(id="companion_kael", name="Kael")
        bg, _, _ = _make_bg(session_data=sd)
        events = [
            GameEvent(
                event_type=E.DISPOSITION_CHANGED,
                payload={"npc_name": "Torin", "previous": "neutral", "new": "friendly"},
            )
        ]
        bg._handle_events(events)
        assert len(bg._speech_queue) == 1
        assert "approves" in bg._speech_queue[0].instructions
        assert sd.companion.emotional_state == "pleased"


class TestCompanionIdleSpeech:
    def test_queues_speech_after_idle(self):
        sd = _make_session_data()
        sd.companion = CompanionState(
            id="companion_kael",
            name="Kael",
            last_speech_time=time.time() - COMPANION_IDLE_SECS - 1,
        )
        bg, _, _ = _make_bg(session_data=sd)
        bg._check_companion_idle()
        assert len(bg._speech_queue) == 1
        assert "COMPANION_KAEL" in bg._speech_queue[0].instructions
        assert bg._speech_queue[0].priority == SpeechPriority.ROUTINE

    def test_skips_during_combat(self):
        cs = CombatState(
            combat_id="test",
            participants=[
                CombatParticipant(id="p1", name="P", type="player", initiative=10, hp_current=10, hp_max=10, ac=10)
            ],
            initiative_order=["p1"],
        )
        sd = _make_session_data(combat_state=cs)
        sd.companion = CompanionState(
            id="companion_kael",
            name="Kael",
            last_speech_time=time.time() - 100,
        )
        bg, _, _ = _make_bg(session_data=sd)
        bg._check_companion_idle()
        assert len(bg._speech_queue) == 0

    def test_skips_when_no_companion(self):
        sd = _make_session_data()
        bg, _, _ = _make_bg(session_data=sd)
        bg._check_companion_idle()
        assert len(bg._speech_queue) == 0

    def test_skips_when_unconscious(self):
        sd = _make_session_data()
        sd.companion = CompanionState(
            id="companion_kael",
            name="Kael",
            is_conscious=False,
            last_speech_time=time.time() - 100,
        )
        bg, _, _ = _make_bg(session_data=sd)
        bg._check_companion_idle()
        assert len(bg._speech_queue) == 0

    def test_skips_when_no_speech_time(self):
        sd = _make_session_data()
        sd.companion = CompanionState(id="companion_kael", name="Kael", last_speech_time=0)
        bg, _, _ = _make_bg(session_data=sd)
        bg._check_companion_idle()
        assert len(bg._speech_queue) == 0


class TestQuestHints:
    def test_scene_beat_hint_with_companion_uses_kael(self):
        sd = _make_session_data()
        sd.companion = CompanionState(id="companion_kael", name="Kael")
        past = time.time() - 50
        sd.last_player_speech_time = past
        sd.last_agent_speech_end = past
        bg, _, _ = _make_bg(session_data=sd)
        bg._quest_cache = [
            {
                "quest_id": "greyvale_anomaly",
                "quest_name": "The Greyvale Anomaly",
                "current_stage": 0,
                "stages": [{"id": "s0", "objective": "Travel."}],
                "scene_graph": [{"scene_id": "scene_road", "stage_refs": [0]}],
            }
        ]
        bg._scene_cache = {
            "scene_road": {
                "id": "scene_road",
                "name": "Road",
                "type": "quest",
                "region_type": "wilderness",
                "instructions": "Travel.",
                "beats": [
                    {
                        "id": "b1",
                        "description": "Depart.",
                        "completion_condition": "Go north",
                        "companion_hints": ["Head north to Millhaven."],
                        "hint_delay_seconds": 45,
                    },
                ],
            },
        }
        bg._check_scene_beat_hints()
        assert len(bg._speech_queue) == 1
        assert "COMPANION_KAEL" in bg._speech_queue[0].instructions
        assert "Head north to Millhaven." in bg._speech_queue[0].instructions


class TestEmotionalState:
    def test_location_changed_sets_curious(self):
        sd = _make_session_data()
        sd.companion = CompanionState(id="companion_kael", name="Kael")
        bg, _, _ = _make_bg(session_data=sd)
        events = [GameEvent(event_type=E.LOCATION_CHANGED, payload={"new_location": "market"})]
        bg._handle_events(events)
        assert sd.companion.emotional_state == "curious"

    def test_quest_updated_sets_focused(self):
        sd = _make_session_data()
        sd.companion = CompanionState(id="companion_kael", name="Kael")
        bg, _, _ = _make_bg(session_data=sd)
        events = [GameEvent(event_type=E.QUEST_UPDATED, payload={"quest_name": "Test", "objective": "Do"})]
        bg._handle_events(events)
        assert sd.companion.emotional_state == "focused"

    def test_combat_ended_sets_relieved(self):
        sd = _make_session_data()
        sd.companion = CompanionState(id="companion_kael", name="Kael")
        bg, _, _ = _make_bg(session_data=sd)
        events = [GameEvent(event_type=E.COMBAT_ENDED, payload={"outcome": "victory"})]
        bg._handle_events(events)
        assert sd.companion.emotional_state == "relieved"

    def test_negative_disposition_sets_troubled(self):
        sd = _make_session_data()
        sd.companion = CompanionState(id="companion_kael", name="Kael")
        bg, _, _ = _make_bg(session_data=sd)
        events = [
            GameEvent(
                event_type=E.DISPOSITION_CHANGED,
                payload={"npc_name": "Torin", "previous": "friendly", "new": "neutral"},
            )
        ]
        bg._handle_events(events)
        assert sd.companion.emotional_state == "troubled"


class TestDeliverSpeechUpdatesCompanionTime:
    @pytest.mark.asyncio
    async def test_companion_speech_updates_last_speech_time(self):
        sd = _make_session_data()
        sd.companion = CompanionState(id="companion_kael", name="Kael", last_speech_time=0)
        bg, _, _session = _make_bg(session_data=sd)
        from bg_speech import PendingSpeech

        bg._speech_queue = [
            PendingSpeech(priority=SpeechPriority.IMPORTANT, instructions="Use [COMPANION_KAEL, calm] tag."),
        ]
        await bg._deliver_speech()
        assert sd.companion.last_speech_time > 0
