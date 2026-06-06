"""Unit tests for tool_preconditions — Stage-backed Act guards (raise ToolError)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError

from tool_preconditions import require_npc_present


@pytest.mark.asyncio
async def test_require_npc_present_passes_when_npc_scheduled_here():
    queries = MagicMock()
    queries.get_npcs_at_location = AsyncMock(return_value=[{"id": "guildmaster_torin"}, {"id": "elder_yanna"}])
    # Present at the location → no raise.
    await require_npc_present("accord_guild_hall", "guildmaster_torin", queries=queries)
    queries.get_npcs_at_location.assert_awaited_once_with("accord_guild_hall")


@pytest.mark.asyncio
async def test_require_npc_present_raises_when_npc_absent():
    queries = MagicMock()
    queries.get_npcs_at_location = AsyncMock(return_value=[{"id": "elder_yanna"}])
    with pytest.raises(ToolError, match="isn't here"):
        await require_npc_present("accord_guild_hall", "guildmaster_torin", queries=queries)


@pytest.mark.asyncio
async def test_require_npc_present_raises_when_no_npcs_at_location():
    queries = MagicMock()
    queries.get_npcs_at_location = AsyncMock(return_value=[])
    with pytest.raises(ToolError, match="isn't here"):
        await require_npc_present("greyvale_wilderness_north", "guildmaster_torin", queries=queries)
