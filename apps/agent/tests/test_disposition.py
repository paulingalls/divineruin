"""Tests for the shared resolve_disposition helper (fe1c95e4688c).

Covers the three fallback branches: a recorded per-player disposition, the NPC's
content default_disposition, and the final 'neutral' default.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from disposition import resolve_disposition


def _mods(*, recorded, default=None, npc_exists=True):
    queries = MagicMock()
    queries.get_npc_disposition = AsyncMock(return_value=recorded)
    content = MagicMock()
    content.get_npc = AsyncMock(
        return_value=({"default_disposition": default} if default is not None else {}) if npc_exists else None
    )
    return queries, content


@pytest.mark.asyncio
async def test_returns_recorded_disposition_without_content_lookup():
    queries, content = _mods(recorded="friendly", default="hostile")
    result = await resolve_disposition("npc_1", "player_1", queries_mod=queries, content_mod=content)
    assert result == "friendly"
    content.get_npc.assert_not_awaited()  # recorded standing short-circuits the content read


@pytest.mark.asyncio
async def test_falls_back_to_content_default_disposition():
    queries, content = _mods(recorded=None, default="trusted")
    result = await resolve_disposition("npc_1", "player_1", queries_mod=queries, content_mod=content)
    assert result == "trusted"


@pytest.mark.asyncio
async def test_falls_back_to_neutral_when_no_record_and_no_npc():
    queries, content = _mods(recorded=None, npc_exists=False)
    result = await resolve_disposition("npc_1", "player_1", queries_mod=queries, content_mod=content)
    assert result == "neutral"


@pytest.mark.asyncio
async def test_threads_conn_and_for_update_to_the_disposition_read():
    queries, content = _mods(recorded="neutral")
    sentinel = object()
    await resolve_disposition(
        "npc_1", "player_1", conn=sentinel, for_update=True, queries_mod=queries, content_mod=content
    )
    kwargs = queries.get_npc_disposition.await_args.kwargs
    assert kwargs["conn"] is sentinel and kwargs["for_update"] is True
