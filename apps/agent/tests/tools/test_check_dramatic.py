"""Story-005: dramatic+context on out-of-combat DICE_ROLL events.

Skill checks and saving throws emitted by check_tools must surface the pure
resolver's dramatic verdict (nat-20 / nat-1 only, out of combat) onto the
client-facing DICE_ROLL payload. Narrative dice stay non-dramatic. Mirrors the
story-004 combat-emission contract.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import check_resolution
import event_types as E
from check_tools import _check_dice_impl, _check_save_impl, _check_skill_impl
from tools._helpers import _make_context, _make_mock_room

SAMPLE_PLAYER = {
    "player_id": "player_1",
    "name": "Kael",
    "class": "warrior",
    "level": 1,
    "attributes": {
        "strength": 14,
        "dexterity": 12,
        "constitution": 13,
        "intelligence": 10,
        "wisdom": 11,
        "charisma": 8,
    },
    "proficiencies": ["athletics", "stealth", "perception"],
    "saving_throw_proficiencies": ["strength", "constitution"],
    "hp": {"current": 25, "max": 25},
    "ac": 14,
}


def _skill_mocks():
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
    queries.get_single_skill_advancement = AsyncMock(
        return_value={"tier": "untrained", "use_counter": 0, "narrative_moment_ready": False},
    )
    mutations = MagicMock()
    mutations.update_skill_advancement = AsyncMock()
    return queries, mutations


def _save_mocks():
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
    return queries


@pytest.fixture
def force_d20(monkeypatch):
    """Force the next d20 roll to a fixed face value at the shared roll seam."""

    def _set(face):
        monkeypatch.setattr(check_resolution, "dice_roll", lambda notation, rng=None: SimpleNamespace(total=face))

    return _set


def _dice_event(room):
    for call in room.local_participant.publish_data.call_args_list:
        payload = json.loads(call[0][0])
        if payload.get("type") == E.DICE_ROLL:
            return payload
    raise AssertionError("no DICE_ROLL event was published")


class TestSkillCheckDramatic:
    @pytest.mark.asyncio
    async def test_nat20_is_dramatic(self, force_d20):
        force_d20(20)
        queries, mutations = _skill_mocks()
        room = _make_mock_room()
        await _check_skill_impl(
            _make_context(room=room), "stealth", "moderate", "sneaking", queries=queries, mutations=mutations
        )
        payload = _dice_event(room)
        assert payload["roll_type"] == "skill_check"
        assert payload["dramatic"] is True
        assert payload["context"] == "natural_20"

    @pytest.mark.asyncio
    async def test_nat1_is_dramatic(self, force_d20):
        force_d20(1)
        queries, mutations = _skill_mocks()
        room = _make_mock_room()
        await _check_skill_impl(
            _make_context(room=room), "stealth", "moderate", "sneaking", queries=queries, mutations=mutations
        )
        payload = _dice_event(room)
        assert payload["dramatic"] is True
        assert payload["context"] == "natural_1"

    @pytest.mark.asyncio
    async def test_routine_roll_not_dramatic(self, force_d20):
        force_d20(10)
        queries, mutations = _skill_mocks()
        room = _make_mock_room()
        await _check_skill_impl(
            _make_context(room=room), "stealth", "moderate", "sneaking", queries=queries, mutations=mutations
        )
        payload = _dice_event(room)
        assert payload["dramatic"] is False
        assert payload["context"] == ""


class TestSavingThrowDramatic:
    @pytest.mark.asyncio
    async def test_nat20_is_dramatic(self, force_d20):
        force_d20(20)
        room = _make_mock_room()
        await _check_save_impl(_make_context(room=room), "dexterity", 12, "be knocked prone", queries=_save_mocks())
        payload = _dice_event(room)
        assert payload["roll_type"] == "saving_throw"
        assert payload["dramatic"] is True
        assert payload["context"] == "natural_20"

    @pytest.mark.asyncio
    async def test_nat1_is_dramatic(self, force_d20):
        force_d20(1)
        room = _make_mock_room()
        await _check_save_impl(_make_context(room=room), "dexterity", 12, "be knocked prone", queries=_save_mocks())
        payload = _dice_event(room)
        assert payload["dramatic"] is True
        assert payload["context"] == "natural_1"

    @pytest.mark.asyncio
    async def test_routine_save_not_dramatic(self, force_d20):
        force_d20(10)
        room = _make_mock_room()
        await _check_save_impl(_make_context(room=room), "dexterity", 12, "be knocked prone", queries=_save_mocks())
        payload = _dice_event(room)
        assert payload["dramatic"] is False
        assert payload["context"] == ""


class TestNarrativeDiceNeverDramatic:
    @pytest.mark.asyncio
    async def test_narrative_dice_has_no_dramatic_field(self):
        room = _make_mock_room()
        await _check_dice_impl(_make_context(room=room), "2d6")
        payload = _dice_event(room)
        assert payload["roll_type"] == "narrative"
        assert "dramatic" not in payload
