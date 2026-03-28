"""Tests for the card tap hint handler."""

import json
import time
from unittest.mock import MagicMock

import pytest

from card_tap_handler import HINT_COOLDOWN_S, PLAYER_HINTS_TOPIC, CardTapHandler, build_hint_instruction
from creation_data import CLASSES, DEITIES, RACES
from session_data import CreationState, SessionData

# ---------------------------------------------------------------------------
# build_hint_instruction — pure function tests
# ---------------------------------------------------------------------------


class TestBuildHintInstruction:
    @pytest.mark.parametrize("race_id", list(RACES.keys()))
    def test_all_races_produce_hints(self, race_id: str):
        result = build_hint_instruction(race_id, "race")
        assert result is not None
        assert RACES[race_id].name in result

    @pytest.mark.parametrize("class_id", list(CLASSES.keys()))
    def test_all_classes_produce_hints(self, class_id: str):
        result = build_hint_instruction(class_id, "class")
        assert result is not None
        assert CLASSES[class_id].name in result

    @pytest.mark.parametrize("deity_id", [d for d in DEITIES if d != "none"])
    def test_all_deities_produce_hints(self, deity_id: str):
        result = build_hint_instruction(deity_id, "deity")
        assert result is not None
        assert DEITIES[deity_id].name in result

    def test_instruction_uses_full_description(self):
        """Should use the long ear-first description, not card_description."""
        result = build_hint_instruction("elari", "race")
        assert RACES["elari"].description in result

    def test_none_deity_special_case(self):
        result = build_hint_instruction("none", "deity")
        assert result is not None
        assert "without a patron" in result

    def test_invalid_race_returns_none(self):
        assert build_hint_instruction("bogus", "race") is None

    def test_invalid_class_returns_none(self):
        assert build_hint_instruction("bogus", "class") is None

    def test_invalid_deity_returns_none(self):
        assert build_hint_instruction("bogus", "deity") is None

    def test_invalid_category_returns_none(self):
        assert build_hint_instruction("warrior", "weapon") is None


# ---------------------------------------------------------------------------
# CardTapHandler — integration tests
# ---------------------------------------------------------------------------


def _make_data_packet(payload: dict, topic: str = PLAYER_HINTS_TOPIC) -> MagicMock:
    pkt = MagicMock()
    pkt.data = json.dumps(payload).encode()
    pkt.topic = topic
    return pkt


def _make_handler(in_creation: bool = True) -> tuple[CardTapHandler, MagicMock]:
    room = MagicMock()
    session = MagicMock()
    session.generate_reply = MagicMock()
    sd = SessionData(
        player_id="test",
        location_id="",
        room=room,
        creation_state=CreationState() if in_creation else None,
    )
    handler = CardTapHandler(room=room, session=session, userdata=sd)
    return handler, session


class TestCardTapHandler:
    def test_ignores_wrong_topic(self):
        handler, session = _make_handler()
        pkt = _make_data_packet({"type": "creation_card_tap", "card_id": "elari", "category": "race"}, topic="other")
        handler._on_data_received(pkt)
        session.generate_reply.assert_not_called()

    def test_ignores_when_not_in_creation(self):
        handler, session = _make_handler(in_creation=False)
        pkt = _make_data_packet({"type": "creation_card_tap", "card_id": "elari", "category": "race"})
        handler._on_data_received(pkt)
        session.generate_reply.assert_not_called()

    def test_ignores_wrong_type(self):
        handler, session = _make_handler()
        pkt = _make_data_packet({"type": "other_event", "card_id": "elari", "category": "race"})
        handler._on_data_received(pkt)
        session.generate_reply.assert_not_called()

    def test_ignores_invalid_json(self):
        handler, session = _make_handler()
        pkt = MagicMock()
        pkt.data = b"not json"
        pkt.topic = PLAYER_HINTS_TOPIC
        handler._on_data_received(pkt)
        session.generate_reply.assert_not_called()

    def test_ignores_unknown_card(self):
        handler, session = _make_handler()
        pkt = _make_data_packet({"type": "creation_card_tap", "card_id": "bogus", "category": "race"})
        handler._on_data_received(pkt)
        session.generate_reply.assert_not_called()

    def test_valid_hint_triggers_generate_reply(self):
        handler, session = _make_handler()
        pkt = _make_data_packet({"type": "creation_card_tap", "card_id": "warrior", "category": "class"})
        handler._on_data_received(pkt)
        session.generate_reply.assert_called_once()
        call_kwargs = session.generate_reply.call_args[1]
        assert "user_input" in call_kwargs
        assert call_kwargs["tool_choice"] == "none"

    def test_cooldown_prevents_rapid_hints(self):
        handler, session = _make_handler()
        pkt = _make_data_packet({"type": "creation_card_tap", "card_id": "elari", "category": "race"})

        handler._on_data_received(pkt)
        assert session.generate_reply.call_count == 1

        # Second tap within cooldown window
        handler._on_data_received(pkt)
        assert session.generate_reply.call_count == 1  # still 1

    def test_hint_after_cooldown_succeeds(self):
        handler, session = _make_handler()
        pkt = _make_data_packet({"type": "creation_card_tap", "card_id": "elari", "category": "race"})

        handler._on_data_received(pkt)
        assert session.generate_reply.call_count == 1

        # Simulate cooldown expiry
        handler._last_hint_time = time.time() - HINT_COOLDOWN_S - 1
        handler._on_data_received(pkt)
        assert session.generate_reply.call_count == 2

    def test_start_registers_listener(self):
        handler, _ = _make_handler()
        handler.start()
        handler._room.on.assert_called_once_with("data_received", handler._on_data_received)

    def test_stop_unregisters_listener(self):
        handler, _ = _make_handler()
        handler.stop()
        handler._room.off.assert_called_once_with("data_received", handler._on_data_received)
