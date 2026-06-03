"""Tests for end_combat: state clearing, agent handoff, XP calc by outcome, events, errors."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _make_combat_state, _make_context, _make_mock_room
from livekit.agents.llm import ToolError

import event_types as E
from combat_end import _end_combat_impl


def _make_end_combat_mocks():
    """Create mock modules for end_combat DI params."""
    mock_mutations = MagicMock()
    mock_mutations.delete_combat_state = AsyncMock()
    return mock_mutations


class TestEndCombat:
    @pytest.mark.asyncio
    async def test_clears_state(self):
        mock_mutations = _make_end_combat_mocks()
        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state()

        raw = await _end_combat_impl(ctx, outcome="victory", mutations=mock_mutations)
        assert isinstance(raw, tuple), "end_combat success should return (DungeonMasterAgent, json_str)"
        _, json_str = raw
        result = json.loads(json_str)

        assert result["outcome"] == "victory"
        assert ctx.userdata.in_combat is False
        assert ctx.userdata.combat_state is None
        mock_mutations.delete_combat_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_city_agent(self):
        from city_agent import CityAgent

        mock_mutations = _make_end_combat_mocks()
        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state()

        raw = await _end_combat_impl(ctx, outcome="victory", mutations=mock_mutations)
        agent_instance, _ = raw
        assert isinstance(agent_instance, CityAgent)

    @pytest.mark.asyncio
    async def test_returned_agent_has_combat_summary_context(self):
        mock_mutations = _make_end_combat_mocks()
        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state()

        raw = await _end_combat_impl(ctx, outcome="victory", mutations=mock_mutations)
        assert isinstance(raw, tuple)
        agent_instance, _ = raw
        # The returned agent should have a chat_ctx with a combat summary
        items = list(agent_instance.chat_ctx.items)
        assert len(items) > 0

    @pytest.mark.asyncio
    async def test_calculates_xp_on_victory(self):
        mock_mutations = _make_end_combat_mocks()
        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state()

        _, json_str = await _end_combat_impl(ctx, outcome="victory", mutations=mock_mutations)
        result = json.loads(json_str)

        assert result["xp_total"] == 50
        assert "Goblin Scout" in result["defeated_enemies"]

    @pytest.mark.asyncio
    async def test_no_xp_on_defeat(self):
        mock_mutations = _make_end_combat_mocks()
        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state()

        _, json_str = await _end_combat_impl(ctx, outcome="defeat", mutations=mock_mutations)
        result = json.loads(json_str)

        assert result["xp_total"] == 0
        assert result["defeated_enemies"] == []

    @pytest.mark.asyncio
    async def test_no_xp_on_fled(self):
        mock_mutations = _make_end_combat_mocks()
        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state()

        _, json_str = await _end_combat_impl(ctx, outcome="fled", mutations=mock_mutations)
        result = json.loads(json_str)

        assert result["xp_total"] == 0

    @pytest.mark.asyncio
    async def test_publishes_events(self):
        mock_mutations = _make_end_combat_mocks()
        room = _make_mock_room()
        ctx = _make_context(room=room)
        ctx.userdata.combat_state = _make_combat_state()

        await _end_combat_impl(ctx, outcome="victory", mutations=mock_mutations)

        calls = [json.loads(c[0][0]) for c in room.local_participant.publish_data.call_args_list]
        types = [c["type"] for c in calls]
        assert E.COMBAT_ENDED in types
        assert E.PLAY_SOUND in types

    @pytest.mark.asyncio
    async def test_error_if_not_in_combat(self):
        ctx = _make_context()

        with pytest.raises(ToolError, match="Not in combat"):
            await _end_combat_impl(ctx, outcome="victory")

    @pytest.mark.asyncio
    async def test_error_invalid_outcome(self):
        mock_mutations = _make_end_combat_mocks()
        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state()

        with pytest.raises(ToolError, match="Invalid outcome"):
            await _end_combat_impl(ctx, outcome="surrender", mutations=mock_mutations)
