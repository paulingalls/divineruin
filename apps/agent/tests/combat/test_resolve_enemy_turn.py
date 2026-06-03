"""Tests for resolve_enemy_turn: attack resolution, HP/fallen updates, sounds, errors."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _make_combat_state, _make_context, _make_mock_room
from livekit.agents.llm import ToolError

import event_types as E
from combat_turn import _resolve_enemy_turn_impl


def _make_resolve_mocks():
    """Create mock modules for resolve_enemy_turn DI params."""
    mock_mutations = MagicMock()
    mock_mutations.save_combat_state = AsyncMock()
    mock_mutations.update_player_hp = AsyncMock()
    return mock_mutations


def _make_resolve_queries():
    """Mock db_queries for resolve_enemy_turn: no equipped items, so a player hit
    accrues no durability (the accrual path is covered in test_combat_durability)."""
    mock_queries = MagicMock()
    mock_queries.get_player_inventory = AsyncMock(return_value=[])
    return mock_queries


class TestResolveEnemyTurn:
    @pytest.mark.asyncio
    async def test_resolves_attack(self):
        mock_mutations = _make_resolve_mocks()
        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state()

        result = json.loads(
            await _resolve_enemy_turn_impl(
                ctx,
                enemy_id="goblin_scout_1",
                action_name="Scimitar",
                target_id="player_1",
                mutations=mock_mutations,
                queries=_make_resolve_queries(),
            )
        )

        assert "hit" in result
        assert "damage" in result
        assert "narrative_hint" in result
        assert result["attacker"] == "Goblin Scout"
        assert result["target"] == "Kael"
        mock_mutations.save_combat_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_updates_player_hp(self):
        mock_mutations = _make_resolve_mocks()
        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state()

        result = json.loads(
            await _resolve_enemy_turn_impl(
                ctx,
                enemy_id="goblin_scout_1",
                action_name="Scimitar",
                target_id="player_1",
                mutations=mock_mutations,
                queries=_make_resolve_queries(),
            )
        )

        if result["hit"]:
            mock_mutations.update_player_hp.assert_called_once()

    @pytest.mark.asyncio
    async def test_publishes_sounds(self):
        mock_mutations = _make_resolve_mocks()
        room = _make_mock_room()
        ctx = _make_context(room=room)
        ctx.userdata.combat_state = _make_combat_state()

        await _resolve_enemy_turn_impl(
            ctx,
            enemy_id="goblin_scout_1",
            action_name="Scimitar",
            target_id="player_1",
            mutations=mock_mutations,
            queries=_make_resolve_queries(),
        )

        # At minimum: dice_roll event + at least one play_sound
        assert room.local_participant.publish_data.call_count >= 2

    @pytest.mark.asyncio
    async def test_triggers_heartbeat_below_50_percent(self):
        mock_mutations = _make_resolve_mocks()
        room = _make_mock_room()
        ctx = _make_context(room=room)
        # Set player HP to 10/25 = 40%, which is bloodied
        ctx.userdata.combat_state = _make_combat_state(player_hp=10)

        result = json.loads(
            await _resolve_enemy_turn_impl(
                ctx,
                enemy_id="goblin_scout_1",
                action_name="Scimitar",
                target_id="player_1",
                mutations=mock_mutations,
                queries=_make_resolve_queries(),
            )
        )

        if result["hit"] and result["target_hp_status"] in ("bloodied", "critical"):
            calls = [json.loads(c[0][0]) for c in room.local_participant.publish_data.call_args_list]
            sounds = [c.get("sound_name") for c in calls if c.get("type") == E.PLAY_SOUND]
            assert "heartbeat_low_hp" in sounds

    @pytest.mark.asyncio
    async def test_sets_fallen_at_zero_hp(self):
        mock_mutations = _make_resolve_mocks()
        ctx = _make_context()
        # Set player HP to 1 so a hit will bring to 0
        ctx.userdata.combat_state = _make_combat_state(player_hp=1)

        result = json.loads(
            await _resolve_enemy_turn_impl(
                ctx,
                enemy_id="goblin_scout_1",
                action_name="Scimitar",
                target_id="player_1",
                mutations=mock_mutations,
                queries=_make_resolve_queries(),
            )
        )

        if result["hit"]:
            assert result["target_fallen"] is True

    @pytest.mark.asyncio
    async def test_error_not_in_combat(self):
        ctx = _make_context()

        with pytest.raises(ToolError, match="Not in combat"):
            await _resolve_enemy_turn_impl(ctx, enemy_id="goblin_scout_1", action_name="Scimitar", target_id="player_1")

    @pytest.mark.asyncio
    async def test_error_invalid_enemy(self):
        mock_mutations = _make_resolve_mocks()
        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state()

        with pytest.raises(ToolError, match="not found in combat"):
            await _resolve_enemy_turn_impl(
                ctx,
                enemy_id="nonexistent",
                action_name="Scimitar",
                target_id="player_1",
                mutations=mock_mutations,
                queries=_make_resolve_queries(),
            )

    @pytest.mark.asyncio
    async def test_error_invalid_action(self):
        mock_mutations = _make_resolve_mocks()
        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state()

        with pytest.raises(ToolError, match="not found"):
            await _resolve_enemy_turn_impl(
                ctx,
                enemy_id="goblin_scout_1",
                action_name="Fireball",
                target_id="player_1",
                mutations=mock_mutations,
                queries=_make_resolve_queries(),
            )

    @pytest.mark.asyncio
    async def test_error_fallen_target(self):
        mock_mutations = _make_resolve_mocks()
        ctx = _make_context()
        ctx.userdata.combat_state = _make_combat_state(player_fallen=True, player_hp=0)

        with pytest.raises(ToolError, match="already fallen"):
            await _resolve_enemy_turn_impl(
                ctx,
                enemy_id="goblin_scout_1",
                action_name="Scimitar",
                target_id="player_1",
                mutations=mock_mutations,
                queries=_make_resolve_queries(),
            )
