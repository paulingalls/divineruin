import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from livekit.agents.llm import ToolError

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
    async def test_invalid_category_returns_empty(self):
        """Call _func to reach our tool body without recreating vendor dispatch."""
        ctx = _make_context()
        result = json.loads(await _push_cards(ctx, category="invalid"))
        assert result["count"] == 0
        assert result["options"] == []

    async def test_push_cards_does_not_advance_phase(self):
        ctx = _make_context(CreationState(phase="prologue"))
        await _push_cards(ctx, category="race")
        assert ctx.userdata.creation_state.phase == "prologue"


class TestSetCreationChoice:
    async def test_set_name_strips_whitespace(self):
        ctx = _make_context()
        await _set_choice(ctx, category="name", value="  Aric  ")
        assert ctx.userdata.creation_state.name == "Aric"

    async def test_set_empty_name_rejected(self):
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _set_choice(ctx, category="name", value="")

    async def test_invalid_category(self):
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _set_choice(ctx, category="invalid", value="test")

    async def test_not_in_creation_mode(self):
        ctx = _make_context()
        ctx.userdata.creation_state = None
        with pytest.raises(ToolError):
            await _set_choice(ctx, category="race", value="human")
