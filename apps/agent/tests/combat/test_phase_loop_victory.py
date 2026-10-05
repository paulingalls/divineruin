import json

import pytest
from combat._helpers import _resolution_state, _resolve_round
from combat.test_phase_loop import _resolve_deps
from sample_fixtures import make_context

from combat_turn import _declare_phase_impl


class TestPhaseLoopE2E:
    @pytest.mark.asyncio
    async def test_full_lifecycle_to_victory(self):
        deps = _resolve_deps(damage=4)
        ctx = make_context()
        cs = _resolution_state(player_hp=25, enemy_hp=7)
        cs.beat = "declaration"
        cs.pending_declarations = {}
        ctx.userdata.combat_state = cs

        decls = {
            "player_1": {"type": "attack", "action": "Longsword", "target_id": "goblin_scout_1"},
            "goblin_scout_1": {"type": "attack", "action": "Scimitar", "target_id": "player_1"},
        }

        d1 = json.loads(await _declare_phase_impl(ctx, decls, mutations=deps["mutations"]))
        assert d1["beat"] == "resolution"

        r1j = await _resolve_round(ctx, **deps)
        assert not isinstance(r1j, tuple), "round 1 does not end combat"
        assert r1j["beat"] == "declaration" and r1j["round"] == 2
        assert len([p for p in r1j["packets"] if p["resolved"]]) == 2
        goblin = ctx.userdata.combat_state.get_participant("goblin_scout_1")
        assert goblin is not None and goblin.hp_current == 3  # 7 - 4

        await _declare_phase_impl(ctx, decls, mutations=deps["mutations"])
        r2 = await _resolve_round(ctx, **deps)

        assert isinstance(r2, tuple), "the winning wrap returns the (gameplay_agent, json) handoff"
        _agent, json_str = r2
        assert json.loads(json_str)["outcome"] == "victory"
        assert ctx.userdata.combat_state is None
        deps["mutations"].delete_combat_state.assert_awaited_once()
