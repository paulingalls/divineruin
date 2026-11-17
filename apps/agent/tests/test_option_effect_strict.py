"""A decision option whose effect does not parse must refuse, not record a choice that changes nothing."""

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
        ("accord_guild_reputation no_such_event", {"id": "accord_guild"}),
        ("no_such_guild_reputation completed_faction_quest", None),
    ],
    ids=["unknown_effect", "unknown_reputation_event", "unknown_faction"],
)
async def test_strict_option_effect_refuses(effect: str, faction: dict | None) -> None:
    session = SessionData(player_id="player_1", location_id="greyvale_ruins_inner")
    mutations = MagicMock()
    reputation = MagicMock()
    with pytest.raises(ValueError, match="option effect"):
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
            strict=True,
        )
    assert not mutations.method_calls
    assert not reputation.method_calls
