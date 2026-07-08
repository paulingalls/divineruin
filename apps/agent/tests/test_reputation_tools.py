"""Tests for the adjust_faction_reputation DM tool (story-002, M23).

Mirrors the update_npc_disposition tool tests: validate the faction exists, map the named
event to a delta via the pure resolver, apply it via the writer, and return a narratable
JSON payload. Injected content/mutations mocks keep it pure-unit (the real writer is covered
by test_db_mutations_reputation).
"""

import json
from unittest.mock import AsyncMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context as _make_context

from reputation_tools import _adjust_faction_reputation_impl


def _content(faction=None):
    m = AsyncMock()
    m.get_faction.return_value = faction
    return m


async def test_applies_delta_and_returns_new_standing():
    ctx = _make_context(player_id="p1")
    content = _content({"name": "The Accord Guild"})
    mutations = AsyncMock()
    mutations.adjust_player_faction_reputation.return_value = 5

    out = json.loads(
        await _adjust_faction_reputation_impl(
            ctx,
            "accord_guild",
            "completed_faction_quest",
            "cleared the ruins",
            mutations=mutations,
            content=content,
        )
    )

    assert out["delta"] == 5
    assert out["new_value"] == 5
    assert out["faction_name"] == "The Accord Guild"
    assert out["event_type"] == "completed_faction_quest"
    mutations.adjust_player_faction_reputation.assert_awaited_once_with("p1", "accord_guild", 5, "cleared the ruins")


async def test_penalty_event_lowers_standing():
    ctx = _make_context(player_id="p1")
    mutations = AsyncMock()
    mutations.adjust_player_faction_reputation.return_value = -3
    out = json.loads(
        await _adjust_faction_reputation_impl(
            ctx,
            "accord_guild",
            "killed_faction_member",
            "slew the patrol",
            mutations=mutations,
            content=_content({"name": "Accord"}),
        )
    )
    assert out["delta"] == -3
    assert out["new_value"] == -3


async def test_unknown_faction_fails_loud():
    ctx = _make_context()
    with pytest.raises(ToolError, match="not found"):
        await _adjust_faction_reputation_impl(
            ctx,
            "no_such_faction",
            "aided_faction",
            "helped",
            mutations=AsyncMock(),
            content=_content(None),
        )


async def test_unknown_event_fails_loud():
    ctx = _make_context()
    mutations = AsyncMock()
    with pytest.raises(ToolError, match="unknown reputation event"):
        await _adjust_faction_reputation_impl(
            ctx,
            "accord_guild",
            "smiled_politely",
            "grinned",
            mutations=mutations,
            content=_content({"name": "Accord"}),
        )
    mutations.adjust_player_faction_reputation.assert_not_awaited()


async def test_reason_too_long_fails_loud():
    ctx = _make_context()
    with pytest.raises(ToolError):
        await _adjust_faction_reputation_impl(
            ctx,
            "accord_guild",
            "aided_faction",
            "x" * 300,
            mutations=AsyncMock(),
            content=_content({"name": "Accord"}),
        )
