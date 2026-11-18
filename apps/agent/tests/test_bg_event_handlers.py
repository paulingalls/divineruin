from unittest.mock import MagicMock, patch

import pytest

import event_types as E
from bg_event_handlers import REBUILD_EVENT_TYPES, handle_events, queue_god_whisper
from event_bus import GameEvent
from god_whisper_data import get_god_profile
from session_data import SessionData


def _sd() -> SessionData:
    return SessionData(player_id="player_1", location_id="accord_guild_hall")


def _dispatch(events: list[GameEvent], sd: SessionData | None = None) -> tuple[bool, SessionData]:
    sd = sd or _sd()
    needs_rebuild = handle_events(events, sd, [])
    return needs_rebuild, sd


class TestHiddenRevealed:
    def test_in_rebuild_event_types(self):
        assert E.HIDDEN_REVEALED in REBUILD_EVENT_TYPES

    def test_triggers_rebuild(self):
        needs_rebuild, _ = _dispatch([GameEvent(event_type=E.HIDDEN_REVEALED, payload={"element_id": "secret_door"})])
        assert needs_rebuild is True

    def test_records_element_id(self):
        _, sd = _dispatch([GameEvent(event_type=E.HIDDEN_REVEALED, payload={"element_id": "secret_door"})])
        assert sd.recently_revealed_element_ids == ["secret_door"]

    def test_missing_element_id_records_nothing(self):
        _, sd = _dispatch([GameEvent(event_type=E.HIDDEN_REVEALED, payload={})])
        assert sd.recently_revealed_element_ids == []

    def test_batch_with_other_events_still_records(self):
        events = [
            GameEvent(event_type=E.DICE_ROLL, payload={}),
            GameEvent(event_type=E.HIDDEN_REVEALED, payload={"element_id": "loose_brick"}),
        ]
        needs_rebuild, sd = _dispatch(events)
        assert needs_rebuild is True
        assert sd.recently_revealed_element_ids == ["loose_brick"]

    def test_multiple_reveals_accumulate_in_order(self):
        events = [
            GameEvent(event_type=E.HIDDEN_REVEALED, payload={"element_id": "a"}),
            GameEvent(event_type=E.HIDDEN_REVEALED, payload={"element_id": "b"}),
        ]
        _, sd = _dispatch(events)
        assert sd.recently_revealed_element_ids == ["a", "b"]


def test_absent_players_crossing_queues_nothing():
    speech = []
    handle_events([GameEvent(E.DIVINE_FAVOR_CHANGED, {"player_id": "absent", "amount": 5})], _sd(), speech)
    assert speech == []


def test_whisper_fallback_uses_new_primary_patron():
    sd = SessionData(player_id="host", location_id="hall", patron_id="solwyn")
    sd.party.members.append(SessionData(player_id="p2", location_id="hall", patron_id="thessyn").party.primary)
    sd.handoff_primary("host")
    with patch("bg_event_handlers.get_god_profile", return_value=MagicMock()) as profile:
        queue_god_whisper({}, sd, [])
    profile.assert_called_once_with("thessyn")


def test_displeasure_without_patron_profile_raises():
    speech = []
    with pytest.raises(ValueError, match="No displeasure_prompt for patron not_a_god"):
        queue_god_whisper({"patron_id": "not_a_god"}, _sd(), speech, displeasure=True)
    assert speech == []


def _favor_event(amount: int, reason: str, player_id: str = "player_1") -> GameEvent:
    return GameEvent(
        event_type=E.DIVINE_FAVOR_CHANGED,
        payload={
            "player_id": player_id,
            "patron_id": "kaelen",
            "previous_level": 30 - amount,
            "new_level": 30,
            "max": 100,
            "requested_amount": amount,
            "last_whisper_level": 0,
            "amount": amount,
            "reason": reason,
        },
    )


def test_positive_due_favor_remains_ordinary_and_zero_queues_nothing():
    sd = _sd()
    speech = []
    handle_events([_favor_event(0, "none")], sd, speech)
    assert speech == []
    handle_events([_favor_event(5, "valor")], sd, speech)
    assert len(speech) == 1
    assert not speech[0].is_displeasure
    assert get_god_profile("kaelen").displeasure_prompt not in speech[0].instructions


def test_favor_event_requires_amount():
    payload = _favor_event(5, "valor").payload
    del payload["amount"]
    with pytest.raises(KeyError, match="amount"):
        handle_events([GameEvent(event_type=E.DIVINE_FAVOR_CHANGED, payload=payload)], _sd(), [])
