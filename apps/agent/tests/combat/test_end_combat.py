"""Tests for end_combat: state clearing, agent handoff, XP calc by outcome, events, errors."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import (
    _damage_resolver,
    _fake_db_mod,
    _make_combat_state,
    _resolution_state,
)
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_mock_room

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
        ctx = make_context()
        ctx.userdata.combat_state = _make_combat_state()

        raw = await _end_combat_impl(ctx, outcome="victory", mutations=mock_mutations, db_mod=_fake_db_mod())
        assert isinstance(raw, tuple), "end_combat success should return (DungeonMasterAgent, json_str)"
        _, json_str = raw
        result = json.loads(json_str)

        assert result["outcome"] == "victory"
        assert ctx.userdata.in_combat is False
        assert ctx.userdata.combat_state is None
        mock_mutations.delete_combat_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_city_agent(self):
        from exploration_agent import ExplorationAgent

        mock_mutations = _make_end_combat_mocks()
        ctx = make_context()
        ctx.userdata.combat_state = _make_combat_state()

        raw = await _end_combat_impl(ctx, outcome="victory", mutations=mock_mutations, db_mod=_fake_db_mod())
        agent_instance, _ = raw
        assert isinstance(agent_instance, ExplorationAgent)
        assert agent_instance._agent_type == "city"

    @pytest.mark.asyncio
    async def test_returned_agent_has_combat_summary_context(self):
        mock_mutations = _make_end_combat_mocks()
        ctx = make_context()
        ctx.userdata.combat_state = _make_combat_state()

        raw = await _end_combat_impl(ctx, outcome="victory", mutations=mock_mutations, db_mod=_fake_db_mod())
        assert isinstance(raw, tuple)
        agent_instance, _ = raw
        # The returned agent should have a chat_ctx with a combat summary
        items = list(agent_instance.chat_ctx.items)
        assert len(items) > 0

    @pytest.mark.asyncio
    async def test_calculates_xp_on_victory(self):
        mock_mutations = _make_end_combat_mocks()
        ctx = make_context()
        ctx.userdata.combat_state = _make_combat_state()

        _, json_str = await _end_combat_impl(ctx, outcome="victory", mutations=mock_mutations, db_mod=_fake_db_mod())
        result = json.loads(json_str)

        assert result["xp_total"] == 50
        assert "Goblin Scout" in result["defeated_enemies"]

    @pytest.mark.asyncio
    async def test_no_xp_on_defeat(self, monkeypatch):
        import db_queries

        # No player row in this unit's mock DB -> resurrection (M4.4 defeat path) skips cleanly;
        # this test asserts XP only, not the resurrection flow.
        monkeypatch.setattr(db_queries, "get_player", AsyncMock(return_value=None))
        mock_mutations = _make_end_combat_mocks()
        ctx = make_context()
        ctx.userdata.combat_state = _make_combat_state()

        _, json_str = await _end_combat_impl(ctx, outcome="defeat", mutations=mock_mutations, db_mod=_fake_db_mod())
        result = json.loads(json_str)

        assert result["xp_total"] == 0
        assert result["defeated_enemies"] == []

    @pytest.mark.asyncio
    async def test_no_xp_on_fled(self):
        mock_mutations = _make_end_combat_mocks()
        ctx = make_context()
        ctx.userdata.combat_state = _make_combat_state()

        _, json_str = await _end_combat_impl(ctx, outcome="fled", mutations=mock_mutations, db_mod=_fake_db_mod())
        result = json.loads(json_str)

        assert result["xp_total"] == 0

    @pytest.mark.asyncio
    async def test_publishes_events(self):
        mock_mutations = _make_end_combat_mocks()
        room = make_mock_room()
        ctx = make_context(room=room)
        ctx.userdata.combat_state = _make_combat_state()

        await _end_combat_impl(ctx, outcome="victory", mutations=mock_mutations, db_mod=_fake_db_mod())

        calls = [json.loads(c[0][0]) for c in room.local_participant.publish_data.call_args_list]
        types = [c["type"] for c in calls]
        assert E.COMBAT_ENDED in types
        assert E.PLAY_SOUND in types

    @pytest.mark.asyncio
    async def test_error_if_not_in_combat(self):
        ctx = make_context()

        with pytest.raises(ToolError, match="Not in combat"):
            await _end_combat_impl(ctx, outcome="victory")

    @pytest.mark.asyncio
    async def test_error_invalid_outcome(self):
        mock_mutations = _make_end_combat_mocks()
        ctx = make_context()
        ctx.userdata.combat_state = _make_combat_state()

        with pytest.raises(ToolError, match="Invalid outcome"):
            await _end_combat_impl(ctx, outcome="surrender", mutations=mock_mutations, db_mod=_fake_db_mod())


class TestPhaseLoopExit:
    """Combat now exits through the phase engine's wrap end-condition (story-003):
    resolve_phase fires end_combat when the engine reports victory/defeat, rather than
    the LLM choosing to call end_combat itself. These pin that exit handoff."""

    @pytest.mark.asyncio
    async def test_victory_wrap_hands_back_to_exploration_agent(self):
        from combat_turn import _resolve_phase_impl
        from exploration_agent import ExplorationAgent

        # enemy_hp=3 is one fixed-damage hit from victory; _damage_resolver(3) lands it.
        resolver = _damage_resolver(3)
        queries = MagicMock()
        queries.get_player_inventory = AsyncMock(return_value=[])
        break_mod = MagicMock()
        break_mod.break_concentration_on_damage = AsyncMock(return_value=None)

        ctx = make_context()
        ctx.userdata.combat_state = _resolution_state(player_hp=25, enemy_hp=3)

        raw = await _resolve_phase_impl(
            ctx,
            mutations=_make_end_combat_mocks(),
            queries=queries,
            resolver=resolver,
            concentration_break_mod=break_mod,
            db_mod=_fake_db_mod(),
        )

        assert isinstance(raw, tuple), "a winning wrap should return the (ExplorationAgent, json) handoff"
        agent_instance, json_str = raw
        assert isinstance(agent_instance, ExplorationAgent)
        assert json.loads(json_str)["outcome"] == "victory"
        assert ctx.userdata.combat_state is None
