"""Unsupported quest effects must refuse before recording progress."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from quest_world_effects import _apply_world_effects
from session_data import SessionData


def _content(faction: dict | None) -> MagicMock:
    content = MagicMock()
    content.get_faction = AsyncMock(return_value=faction)
    return content


@pytest.mark.parametrize(
    ("effect", "faction"),
    [
        ("companion_dispositon +3", None),
        ("millhaven_morale +2", None),
        ("event:ruins_discovery_ripple", None),
        ("greyvale_corruption +1", None),
        ("accord_guild_reputation no_such_event", {"id": "accord_guild"}),
        ("no_such_guild_reputation completed_faction_quest", None),
    ],
)
async def test_unsupported_effect_refuses(effect: str, faction: dict | None) -> None:
    session = SessionData(player_id="player_1", location_id="greyvale_ruins_inner")
    mutations = MagicMock()
    reputation = MagicMock()
    with pytest.raises(ValueError, match="effect"):
        await _apply_world_effects(
            [effect],
            session,
            [],
            conn=MagicMock(),
            mutations=mutations,
            queries=MagicMock(),
            content=_content(faction),
            reputation_mutations=reputation,
            party_ids=("player_1",),
        )
    assert not mutations.method_calls
    assert not reputation.method_calls


async def test_absent_companion_refuses():
    from livekit.agents.llm import ToolError

    with pytest.raises(ToolError, match="bound companion"):
        await _apply_world_effects(["companion_disposition +3"], SessionData(player_id="p", location_id="l"), [])
