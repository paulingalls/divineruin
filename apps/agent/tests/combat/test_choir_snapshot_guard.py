"""Pre-affinity Choir snapshots must fail before silently accepting physical damage."""

from unittest.mock import AsyncMock

import pytest
from combat.test_choir_encounter import start_choir

from combat_damage import apply_attack_result
from combat_damage_results import AutomaticDamageResult
from session_data import CombatState


async def test_old_choir_snapshot_requires_reset(mock_combat_agent_factory):
    ctx, _, mutations, queries = await start_choir()
    raw = ctx.userdata.combat_state.to_dict()
    for p in raw["participants"]:
        p.pop("damage_affinities", None)
    state = CombatState.from_dict(raw)
    assert state.choir_encounter is not None
    state.choir_encounter["phase"] = "exposed"
    target = next(p for p in state.participants if p.creature_id == "hollow_choir")
    hp = target.hp_current
    with pytest.raises(ValueError, match="reset/reseed old snapshots"):
        await apply_attack_result(
            ctx.userdata,
            state.participants[0],
            {},
            target,
            AutomaticDamageResult(5, "slashing"),
            target.ac,
            combat_state=state,
            mutations=mutations,
            queries=queries,
            publish_roll=False,
            concentration_break_mod=AsyncMock(),
        )
    assert target.hp_current == hp
    mutations.save_combat_state.assert_awaited_once()
