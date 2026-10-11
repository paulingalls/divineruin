"""Legacy combat rows refuse terrain-dependent writes without consulting location content."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod
from voice_condition_fixtures import place_actors

from combat_state import CombatState
from spell_casting import _resolve_cast
from veil_ward_tools import _activate_veil_ward_impl


async def test_legacy_cache_floor_refuses_cast_and_ward_without_writes():
    ctx = make_context()
    ctx.userdata.combat_state = CombatState.from_dict(
        {"combat_id": "legacy", "location_id": "legacy-mountain", "participants": [], "initiative_order": []}
    )
    place_actors(ctx.userdata.combat_state, "player_1")
    player = {"player_id": "player_1", "class": "druid", "level": 9, "focus": {"current": 20, "max": 20}}
    content = MagicMock(get_location_terrain=AsyncMock(side_effect=AssertionError("location fallback")))
    persistence = MagicMock(update_player_resources=AsyncMock())
    resonance = MagicMock(update_player_resonance=AsyncMock())
    combat = MagicMock(save_combat_state=AsyncMock())
    mock_db, conn = make_db_mod()
    known = MagicMock(get_known=AsyncMock(return_value=[{"spell_id": "primal_healing_touch"}]))
    with pytest.raises(ToolError, match="legacy-mountain"):
        await _resolve_cast(
            ctx.userdata,
            "primal_healing_touch",
            conn=conn,
            player=player,
            content_mod=content,
            persistence_mod=persistence,
            resonance_mutations_mod=resonance,
            character_spells_mod=known,
        )
    with pytest.raises(ToolError, match="legacy-mountain"):
        await _activate_veil_ward_impl(
            ctx,
            True,
            db_mod=mock_db,
            queries_mod=MagicMock(get_player=AsyncMock(return_value=player)),
            content_mod=content,
            persistence_mod=persistence,
            combat_mod=combat,
        )
    content.get_location_terrain.assert_not_awaited()
    persistence.update_player_resources.assert_not_awaited()
    resonance.update_player_resonance.assert_not_awaited()
    combat.save_combat_state.assert_not_awaited()
