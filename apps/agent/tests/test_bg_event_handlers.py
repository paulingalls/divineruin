"""Tests for bg_event_handlers.handle_events — the pure event-dispatch function.

Focuses on the M6 E.HIDDEN_REVEALED handler: a successful discovery's reveal event
triggers a warm rebuild AND records the revealed element id on SessionData, which
story-003's hot-layer assembly reads (and clears) to surface the target same-turn.
"""

import event_types as E
from bg_event_handlers import REBUILD_EVENT_TYPES, handle_events
from event_bus import GameEvent
from session_data import SessionData


def _sd() -> SessionData:
    return SessionData(player_id="player_1", location_id="accord_guild_hall")


def _dispatch(events: list[GameEvent], sd: SessionData | None = None) -> tuple[bool, SessionData]:
    sd = sd or _sd()
    needs_rebuild, _ = handle_events(events, sd, [], False, {}, [])
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
        # A reveal event without an element_id is a no-op for the signal (defensive).
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


class TestDivineFavorWhisperIsPrimaryOnly:
    """Quest favor is party-wide (story-002), so one stage publishes a DIVINE_FAVOR_CHANGED per
    member. The whisper path is NOT party-aware: background_process marks last_whisper_level on
    sd.player_id whoever crossed, so an ungated handler would let a teammate's crossing take the
    tick's single CRITICAL speech slot and advance the primary's cadence while never advancing its
    own. Gate on the recipient (decision b7c3a66f1b74)."""

    _CROSSING = {"new_level": 30, "last_whisper_level": 0, "patron_id": "solwyn"}

    def test_primarys_crossing_queues_a_whisper(self):
        sd = _sd()
        speech: list = []
        handle_events(
            [GameEvent(event_type=E.DIVINE_FAVOR_CHANGED, payload={**self._CROSSING, "player_id": "player_1"})],
            sd,
            speech,
            False,
            {},
            [],
        )
        assert len(speech) == 1

    def test_teammates_crossing_queues_nothing(self):
        sd = _sd()
        speech: list = []
        handle_events(
            [GameEvent(event_type=E.DIVINE_FAVOR_CHANGED, payload={**self._CROSSING, "player_id": "player_2"})],
            sd,
            speech,
            False,
            {},
            [],
        )
        assert speech == []

    def test_unstamped_crossing_still_whispers(self):
        # Back-compat: the award_divine_favor tool path predates the recipient stamp.
        sd = _sd()
        speech: list = []
        handle_events([GameEvent(event_type=E.DIVINE_FAVOR_CHANGED, payload=self._CROSSING)], sd, speech, False, {}, [])
        assert len(speech) == 1
