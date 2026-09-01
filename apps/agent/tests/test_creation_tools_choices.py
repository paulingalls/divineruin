"""Tests for the creation choice-collection tools.

push_creation_cards / set_creation_choice — the card-push, choice-confirmation and
phase-advance behaviors. Split from test_creation_tools_flow.py (finalize + end-to-end)
to stay under the 500-line cap.
"""

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from livekit.agents.llm import ToolError

from creation_classes import CLASSES
from creation_deities import DEITIES
from creation_races import RACES
from creation_tools import push_creation_cards, set_creation_choice
from session_data import CreationState, SessionData

# _func bypasses SDK Literal validation — use Any-typed refs so Pyright accepts
# values outside the Literal (e.g. "race", "invalid") that the underlying code handles.
_push_cards: Any = push_creation_cards._func
_set_choice: Any = set_creation_choice._func


def _make_context(creation_state: CreationState | None = None) -> MagicMock:
    """Build a mock RunContext with SessionData containing a creation state."""
    sd = SessionData(
        player_id="test_player",
        location_id="",
        room=None,
        creation_state=creation_state or CreationState(),
    )
    ctx = MagicMock()
    ctx.userdata = sd
    return ctx


class TestPushCreationCards:
    async def test_race_returns_six_cards(self):
        ctx = _make_context()
        result = json.loads(await _push_cards(ctx, category="race"))
        assert result["count"] == 6
        assert result["category"] == "race"
        ids = {o["id"] for o in result["options"]}
        assert ids == set(RACES.keys())

    async def test_class_returns_all_cards(self):
        ctx = _make_context()
        result = json.loads(await _push_cards(ctx, category="class"))
        assert result["count"] == len(CLASSES)
        assert result["category"] == "class"
        ids = {o["id"] for o in result["options"]}
        assert ids == set(CLASSES.keys())

    async def test_deity_returns_all_plus_none(self):
        ctx = _make_context()
        result = json.loads(await _push_cards(ctx, category="deity"))
        assert result["count"] == len(DEITIES)
        ids = {o["id"] for o in result["options"]}
        assert "none" in ids
        assert "kaelen" in ids

    async def test_invalid_category_returns_empty(self):
        """Literal type validates at SDK level; _func bypass returns empty data."""
        ctx = _make_context()
        result = json.loads(await _push_cards(ctx, category="invalid"))
        assert result["count"] == 0
        assert result["options"] == []

    async def test_race_cards_have_descriptions(self):
        ctx = _make_context()
        result = json.loads(await _push_cards(ctx, category="race"))
        for option in result["options"]:
            assert "description" in option
            assert len(option["description"]) > 10

    async def test_push_cards_does_not_advance_phase(self):
        """Phase should only advance via set_creation_choice, not push_creation_cards."""
        ctx = _make_context(CreationState(phase="prologue"))
        await _push_cards(ctx, category="race")
        assert ctx.userdata.creation_state.phase == "prologue"


class TestSetCreationChoice:
    async def test_set_race_valid(self):
        ctx = _make_context()
        result = json.loads(await _set_choice(ctx, category="race", value="draethar"))
        assert result["confirmed"] == "race"
        assert result["value"] == "draethar"
        assert ctx.userdata.creation_state.race == "draethar"

    async def test_set_race_invalid(self):
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _set_choice(ctx, category="race", value="invalid_race")
        assert ctx.userdata.creation_state.race is None

    async def test_set_class_valid(self):
        ctx = _make_context()
        result = json.loads(await _set_choice(ctx, category="class", value="warrior"))
        assert result["confirmed"] == "class"
        assert ctx.userdata.creation_state.class_choice == "warrior"

    async def test_set_class_invalid(self):
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _set_choice(ctx, category="class", value="invalid_class")

    async def test_set_deity_valid(self):
        ctx = _make_context()
        result = json.loads(await _set_choice(ctx, category="deity", value="kaelen"))
        assert result["confirmed"] == "deity"
        assert ctx.userdata.creation_state.deity == "kaelen"

    async def test_set_deity_none(self):
        ctx = _make_context()
        result = json.loads(await _set_choice(ctx, category="deity", value="none"))
        assert result["confirmed"] == "deity"
        assert ctx.userdata.creation_state.deity == "none"

    async def test_set_deity_invalid(self):
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _set_choice(ctx, category="deity", value="fake_god")

    async def test_set_name(self):
        ctx = _make_context()
        result = json.loads(await _set_choice(ctx, category="name", value="Aric"))
        assert result["confirmed"] == "name"
        assert ctx.userdata.creation_state.name == "Aric"

    async def test_set_name_strips_whitespace(self):
        ctx = _make_context()
        await _set_choice(ctx, category="name", value="  Aric  ")
        assert ctx.userdata.creation_state.name == "Aric"

    async def test_set_empty_name_rejected(self):
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _set_choice(ctx, category="name", value="")

    async def test_set_backstory(self):
        ctx = _make_context()
        result = json.loads(await _set_choice(ctx, category="backstory", value="Born in the Accord."))
        assert result["confirmed"] == "backstory"
        assert ctx.userdata.creation_state.backstory == "Born in the Accord."

    async def test_invalid_category(self):
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _set_choice(ctx, category="invalid", value="test")

    async def test_not_in_creation_mode(self):
        ctx = _make_context()
        ctx.userdata.creation_state = None
        with pytest.raises(ToolError):
            await _set_choice(ctx, category="race", value="human")

    async def test_phase_advances_on_race(self):
        ctx = _make_context(CreationState(phase="awakening"))
        await _set_choice(ctx, category="race", value="human")
        assert ctx.userdata.creation_state.phase == "calling"

    async def test_phase_advances_on_class(self):
        ctx = _make_context(CreationState(phase="calling"))
        await _set_choice(ctx, category="class", value="warrior")
        assert ctx.userdata.creation_state.phase == "devotion"

    async def test_phase_advances_on_deity(self):
        ctx = _make_context(CreationState(phase="devotion"))
        await _set_choice(ctx, category="deity", value="kaelen")
        assert ctx.userdata.creation_state.phase == "identity"

    async def test_progress_tracking(self):
        ctx = _make_context()
        await _set_choice(ctx, category="race", value="human")
        await _set_choice(ctx, category="class", value="warrior")
        result = json.loads(await _set_choice(ctx, category="deity", value="kaelen"))
        progress = result["progress"]
        assert progress["race"] == "human"
        assert progress["class"] == "warrior"
        assert progress["deity"] == "kaelen"
        assert progress["name"] is None

    async def test_guidance_shows_remaining(self):
        ctx = _make_context()
        result = json.loads(await _set_choice(ctx, category="race", value="human"))
        assert "class" in result["guidance"]
