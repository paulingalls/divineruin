"""Tests for the live phase-loop tools (story-003): declare_phase + resolve_phase.

These drive the deterministic 4-beat engine (combat_phase.advance_combat_phase) from
the live CombatAgent: declare_phase collects a phase's declarations (DECLARATION ->
RESOLUTION); resolve_phase resolves the packets, narrates (engine no-op), wraps, and
either loops to the next declaration beat or fires the end-of-combat handoff.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _make_combat_state, _make_context
from livekit.agents.llm import ToolError

from combat_turn import _declare_phase_impl


def _make_mutations():
    m = MagicMock()
    m.save_combat_state = AsyncMock()
    return m


def _declarations():
    return {
        "player_1": {"action": "Longsword", "target_id": "goblin_scout_1"},
        "goblin_scout_1": {"action": "Scimitar", "target_id": "player_1"},
    }


class TestDeclarePhase:
    @pytest.mark.asyncio
    async def test_advances_to_resolution_and_stores_declarations(self):
        mutations = _make_mutations()
        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state()  # beat defaults to "declaration"

        import json

        result = json.loads(await _declare_phase_impl(ctx, _declarations(), mutations=mutations))

        cs = ctx.userdata.combat_state
        assert cs.beat == "resolution"
        assert cs.pending_declarations == _declarations()
        assert set(result["accepted_actors"]) == {"player_1", "goblin_scout_1"}
        assert result["beat"] == "resolution"
        mutations.save_combat_state.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_declarations_raises(self):
        mutations = _make_mutations()
        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state()

        with pytest.raises(ToolError):
            await _declare_phase_impl(ctx, {}, mutations=mutations)
        mutations.save_combat_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_wrong_beat_raises(self):
        mutations = _make_mutations()
        ctx = _make_context()
        cs = _make_combat_state()
        cs.beat = "resolution"  # not the declaration beat
        ctx.userdata.combat_state = cs

        with pytest.raises(ToolError, match="declaration beat"):
            await _declare_phase_impl(ctx, _declarations(), mutations=mutations)
        mutations.save_combat_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_not_in_combat_raises(self):
        ctx = _make_context()  # no combat_state

        with pytest.raises(ToolError, match="Not in combat"):
            await _declare_phase_impl(ctx, _declarations())
