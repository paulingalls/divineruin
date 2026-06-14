"""Tests for the Vaelti Hyper-awareness 1-round advance warning (story-009).

Two halves of the deferred-event hook: the emitter (publish_vaelti_echo_warning puts a
bus-only VAELTI_ECHO_WARNING event) and the consumer (bg_event_handlers.handle_events
routes that event to a CRITICAL DM-speech instruction). Together they surface the
Vaelti's pre-sense to the DM narration path a beat before the Hollow Echo lands.
"""

from unittest.mock import MagicMock

import event_types as E
import vaelti_echo_warning
from bg_event_handlers import handle_events
from bg_speech import SpeechPriority
from event_bus import GameEvent
from session_data import SessionData


def _sd() -> SessionData:
    return SessionData(player_id="player_1", location_id="accord_guild_hall")


class TestEmitter:
    def test_publishes_warning_event_to_explicit_bus(self):
        bus = MagicMock()
        vaelti_echo_warning.publish_vaelti_echo_warning(MagicMock(), event_bus=bus)
        bus.publish.assert_called_once()
        event = bus.publish.call_args.args[0]
        assert event.event_type == E.VAELTI_ECHO_WARNING
        assert event.payload == {}

    def test_falls_back_to_session_bus(self):
        session = MagicMock()
        vaelti_echo_warning.publish_vaelti_echo_warning(session)
        session.event_bus.publish.assert_called_once()
        assert session.event_bus.publish.call_args.args[0].event_type == E.VAELTI_ECHO_WARNING


class TestConsumer:
    def test_warning_event_queues_one_critical_speech(self):
        queue = []
        handle_events([GameEvent(event_type=E.VAELTI_ECHO_WARNING, payload={})], _sd(), queue, False, {}, [])
        assert len(queue) == 1
        assert queue[0].priority == SpeechPriority.CRITICAL
        assert queue[0].instructions == vaelti_echo_warning.WARNING_INSTRUCTION

    def test_unrelated_event_does_not_queue_the_warning(self):
        queue = []
        handle_events([GameEvent(event_type=E.DICE_ROLL, payload={})], _sd(), queue, False, {}, [])
        assert not any(s.instructions == vaelti_echo_warning.WARNING_INSTRUCTION for s in queue)

    def test_warning_does_not_trigger_warm_rebuild(self):
        # One-shot narration — no warm-layer rebuild needed (not in REBUILD_EVENT_TYPES).
        needs_rebuild, _ = handle_events(
            [GameEvent(event_type=E.VAELTI_ECHO_WARNING, payload={})], _sd(), [], False, {}, []
        )
        assert needs_rebuild is False
