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
    # The process composes the CURRENT agent's static half, so a mock target must answer with
    # a real string (a MagicMock would not join).
    agent.static_prompt = MagicMock(return_value="STATIC")
    session = MagicMock()
    session.current_agent = agent
    session.generate_reply = AsyncMock()
    bg = BackgroundProcess(session=session, session_data=sd)
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


def _in_combat(sd: SessionData) -> None:
    sd.combat_state = CombatState(
        combat_id="c1",
        participants=[
            CombatParticipant(id="player_1", name="Kael", type="player", initiative=15, hp_current=20, hp_max=20, ac=14)
        ],
        initiative_order=["player_1"],
    )


class TestProactiveSpeechDoesNotInterruptAFight:
    """story-023 gave the loop SESSION lifetime, so it now runs THROUGH a fight.

    On trunk the process was stopped by ExplorationAgent.on_exit at the handoff into combat, so
    proactive speech could not reach a fight however it was queued. Session-scoped, it can: the
    event-driven producers in ``handle_events`` carry no combat gate, and ``_deliver_speech`` calls
    ``generate_reply`` regardless — so a quest that ticks over on a killing blow makes the DM break
    off mid-beat to narrate an objective. That proactive speech must be suppressed in a fight is
    the module's own position, stated twice: ``_check_companion_idle`` and
    ``_check_scene_beat_hints`` both return early on ``in_combat``. These are the third and fourth
    producers saying it.
    """

    @pytest.mark.asyncio
    async def test_an_event_cue_raised_mid_fight_is_not_spoken(self):
        sd = _make_session_data()
        _in_combat(sd)
        bg, _, session = _make_bg(session_data=sd)
        bg._handle_events(
            [GameEvent(event_type=E.QUEST_UPDATED, payload={"quest_name": "The Rider", "objective": "Ride"})]
        )
        assert bg._speech_queue, "the producer must still queue, or the hold below is vacuous"

        await bg._deliver_speech()

        session.generate_reply.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_it_is_held_rather_than_dropped_and_speaks_once_the_fight_ends(self):
        """Held, not discarded: an event cue is one-shot — nothing re-queues it — so dropping it
        loses a player-facing announcement outright. The idle and hint producers can be skipped
        because a timer remakes them next tick; these cannot."""
        sd = _make_session_data()
        _in_combat(sd)
        bg, _, session = _make_bg(session_data=sd)
        bg._handle_events(
            [GameEvent(event_type=E.QUEST_UPDATED, payload={"quest_name": "The Rider", "objective": "Ride"})]
        )

        await bg._deliver_speech()
        assert len(bg._speech_queue) == 1, "the cue must survive the fight, not be cleared unspoken"

        sd.combat_state = None  # end_combat clears this BEFORE COMBAT_ENDED reaches the bus
        await bg._deliver_speech()

        session.generate_reply.assert_awaited_once()
        assert "The Rider" in session.generate_reply.await_args.kwargs["instructions"]

    @pytest.mark.asyncio
    async def test_the_vaelti_advance_warning_still_speaks_mid_fight(self):
        """The one producer whose whole purpose is to reach the player DURING a fight: a Vaelti
        senses a Hollow Echo one round before it lands (game_mechanics_magic.md:246-252), so a
        blanket gate would delete the mechanic rather than protect it."""
        sd = _make_session_data()
        _in_combat(sd)
        bg, _, session = _make_bg(session_data=sd)
        bg._handle_events([GameEvent(event_type=E.VAELTI_ECHO_WARNING, payload={})])

        await bg._deliver_speech()

        session.generate_reply.assert_awaited_once()
        assert "through the Veil" in session.generate_reply.await_args.kwargs["instructions"]
        assert bg._speech_queue == []

    @pytest.mark.asyncio
    async def test_the_end_of_fight_cue_is_not_outranked_by_what_the_fight_held(self):
        """The hold's one sharp edge, closed deliberately. ``_deliver_speech`` speaks the most
        urgent item and discards the rest, and ``max`` returns the FIRST maximal element — so a cue
        held through the fight would beat the same-priority cue the fight's END raises, which for a
        defeat means a god whisper spoken instead of "the player has fallen". At equal urgency the
        newest event is the one the player is actually in."""
        sd = _make_session_data()
        _in_combat(sd)
        bg, _, session = _make_bg(session_data=sd)
        bg._handle_events(
            [GameEvent(event_type=E.QUEST_UPDATED, payload={"quest_name": "The Rider", "objective": "Ride"})]
        )
        await bg._deliver_speech()

        sd.combat_state = None
        bg._handle_events([GameEvent(event_type=E.COMBAT_ENDED, payload={"outcome": "victory"})])
        await bg._deliver_speech()

        assert "Combat has ended in victory" in session.generate_reply.await_args.kwargs["instructions"]
